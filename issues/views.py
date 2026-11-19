import csv
import json
from datetime import timedelta
from io import BytesIO
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .forms import CommentForm, IssueForm, RegisterForm, StatusUpdateForm
from .models import Category, Department, Issue, Notification, StatusUpdate


KEYWORD_RULES = [
    (['pothole', 'crater', 'asphalt', 'road', 'pavement', 'speedbreaker', 'footpath'], 'Pothole'),
    (['garbage', 'trash', 'waste', 'bin', 'dump', 'sewage', 'smell', 'sanitation'], 'Garbage Overflow'),
    (['light', 'lamp', 'dark', 'pole', 'wire', 'electric', 'spark', 'power'], 'Broken Streetlight'),
    (['water', 'pipe', 'leak', 'flood', 'drain', 'overflow', 'burst'], 'Water Leakage'),
]

UNIT_COST_INR = {
    'Pothole': 4500,
    'Garbage Overflow': 1800,
    'Broken Streetlight': 3200,
    'Water Leakage': 5500,
}


def _is_official(user):
    return user.is_authenticated and (user.is_staff or user.departments.exists())


def _filter_issues(request, queryset):
    q = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()
    status = request.GET.get('status', '').strip()
    department = request.GET.get('department', '').strip()
    sort = request.GET.get('sort', 'recent').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    if q:
        queryset = queryset.filter(
            Q(title__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q)
        )
    if category.isdigit():
        queryset = queryset.filter(category_id=int(category))
    if status == 'overdue':
        queryset = queryset.exclude(status='resolved').filter(due_at__lt=timezone.now())
    elif status in dict(Issue.STATUS_CHOICES):
        queryset = queryset.filter(status=status)
    if department.isdigit():
        queryset = queryset.filter(department_id=int(department))
    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    if sort == 'upvotes':
        queryset = queryset.order_by('-num_upvotes', '-created_at')
    elif sort == 'priority':
        items = sorted(queryset, key=lambda x: x.priority_score, reverse=True)
        selected = {
            'q': q, 'category': category, 'status': status, 'sort': sort,
            'department': department, 'date_from': date_from, 'date_to': date_to,
        }
        filtering = any(v for k, v in selected.items() if k != 'sort')
        return items, selected, filtering
    else:
        queryset = queryset.order_by('-created_at')

    selected = {
        'q': q, 'category': category, 'status': status, 'sort': sort,
        'department': department, 'date_from': date_from, 'date_to': date_to,
    }
    filtering = any(v for k, v in selected.items() if k != 'sort')
    return queryset, selected, filtering


def budget_simulator(request):
    crews = max(1, min(50, int(request.GET.get('crews', 6) or 6)))
    open_issues = Issue.objects.exclude(status='resolved').select_related('category', 'department')
    breakdown = []
    total_cost = 0
    total_hours = 0

    for cat in Category.objects.select_related('department'):
        cnt = open_issues.filter(category=cat).count()
        unit = UNIT_COST_INR.get(cat.name, 3000)
        cost = cnt * unit
        hours = cnt * 4
        total_cost += cost
        total_hours += hours
        breakdown.append({
            'category': cat.name,
            'department': cat.department.name if cat.department else 'General',
            'open_count': cnt,
            'unit_cost': unit,
            'total_cost': cost,
            'crew_hours': hours,
        })

    est_days = round(total_hours / (crews * 8), 1) if total_hours else 0
    return render(request, 'budget_simulator.html', {
        'crews': crews,
        'breakdown': breakdown,
        'total_open': open_issues.count(),
        'total_cost': total_cost,
        'total_hours': total_hours,
        'est_days': est_days,
    })


def executive_brief(request):
    all_issues = list(Issue.objects.select_related('category', 'department', 'reported_by'))
    resolved = [i for i in all_issues if i.status == 'resolved']
    verified = [i for i in resolved if i.citizen_verified]
    overdue = [i for i in all_issues if i.is_overdue]
    resolution_rate = round((len(resolved) / len(all_issues)) * 100, 1) if all_issues else 0
    satisfaction = round((len(verified) / len(resolved)) * 100, 1) if resolved else 100.0
    top_issues = sorted([i for i in all_issues if i.status != 'resolved'], key=lambda x: x.priority_score, reverse=True)[:5]

    return render(request, 'executive_brief.html', {
        'generated_at': timezone.now(),
        'total': len(all_issues),
        'resolved_count': len(resolved),
        'overdue_count': len(overdue),
        'resolution_rate': resolution_rate,
        'satisfaction': satisfaction,
        'top_issues': top_issues,
        'dept_count': Department.objects.count(),
        'citizen_count': User.objects.count(),
    })


def command_pulse_api(request):
    all_issues = list(Issue.objects.all())
    latest = Issue.objects.order_by('-created_at').first()
    return JsonResponse({
        'total': len(all_issues),
        'open': sum(1 for i in all_issues if i.status != 'resolved'),
        'overdue': sum(1 for i in all_issues if i.is_overdue),
        'resolved': sum(1 for i in all_issues if i.status == 'resolved'),
        'latest_id': latest.pk if latest else 0,
        'latest_title': latest.title if latest else '',
    })


@login_required
def set_broadcast(request):
    if not _is_official(request.user) or request.method != 'POST':
        raise PermissionDenied
    msg = request.POST.get('broadcast_msg', '').strip()
    if msg:
        cache.set('civicpulse_emergency_broadcast', msg, timeout=86400)
        messages.warning(request, 'Emergency Civic Alert Banner published citywide!')
    else:
        cache.delete('civicpulse_emergency_broadcast')
        messages.info(request, 'Emergency Alert Banner cleared.')
    return redirect('dashboard')


def civicbot_api(request):
    q = request.GET.get('q', '').lower().strip()
    all_issues = list(Issue.objects.select_related('category', 'department'))
    open_issues = [i for i in all_issues if i.status != 'resolved']
    overdue = [i for i in open_issues if i.is_overdue]

    if 'overdue' in q or 'sla' in q or 'late' in q:
        reply = f"There are currently {len(overdue)} SLA-overdue issues out of {len(open_issues)} open tickets."
    elif 'top' in q or 'urgent' in q or 'critical' in q or 'priority' in q:
        if open_issues:
            top = max(open_issues, key=lambda x: x.priority_score)
            reply = f"Highest priority ticket is #{top.pk} '{top.title}' (Urgency Score: {top.priority_score}, {top.upvote_count} upvotes)."
        else:
            reply = "Great news — there are zero open critical issues right now!"
    elif 'department' in q or 'busy' in q or 'workload' in q:
        depts = Department.objects.annotate(c=Count('issues', filter=~Q(issues__status='resolved'))).order_by('-c')
        if depts:
            reply = f"Busiest department is {depts[0].name} with {depts[0].c} active open issues."
        else:
            reply = "No departments configured yet."
    elif 'budget' in q or 'cost' in q:
        est = sum(UNIT_COST_INR.get(i.category.name, 3000) for i in open_issues)
        reply = f"Estimated municipal repair budget for all {len(open_issues)} open tickets is ₹{est:,}. Open the Budget Simulator for crew projections!"
    elif 'point' in q or 'badge' in q or 'leaderboard' in q:
        reply = "You earn +10 pts per report, +2 pts per neighbor upvote received, and +15 pts when you confirm a repair is fixed!"
    else:
        resolved_count = sum(1 for i in all_issues if i.status == 'resolved')
        reply = (
            f"CivicPulse Live Status: {len(all_issues)} total reports, {len(open_issues)} active, "
            f"{len(overdue)} overdue, and {resolved_count} resolved. Ask about 'overdue', 'top priority', 'budget cost', or 'department workload'!"
        )
    return JsonResponse({'reply': reply})


def architecture(request):
    return render(request, 'architecture.html')


@login_required
def escalate_overdue(request):
    if not _is_official(request.user) or request.method != 'POST':
        raise PermissionDenied
    base_qs, _ = _official_queryset(request.user)
    overdue_issues = base_qs.exclude(status='resolved').filter(due_at__lt=timezone.now())
    count = 0
    for issue in overdue_issues:
        already_escalated = issue.updates.filter(remarks__icontains='AUTO-ESCALATED').exists()
        if not already_escalated:
            StatusUpdate.objects.create(
                issue=issue,
                old_status=issue.status,
                new_status=issue.status,
                updated_by=request.user,
                remarks='AUTO-ESCALATED: SLA target window exceeded. Flagged for immediate supervisor review.',
            )
            Notification.objects.create(
                recipient=issue.reported_by,
                issue=issue,
                message=f"Issue #{issue.pk} exceeded SLA and was auto-escalated to senior officials."
            )
            count += 1
    messages.warning(request, f"SLA Escalation Sweep complete: {count} overdue ticket(s) escalated.")
    return redirect('dashboard')


def home(request):
    base_qs = Issue.objects.select_related('category', 'department').annotate(
        comment_count=Count('comments', distinct=True),
        num_upvotes=Count('upvotes', distinct=True),
    )
    qs, selected, filtering = _filter_issues(request, base_qs)
    total_count = len(qs) if isinstance(qs, list) else qs.count()
    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    params = request.GET.copy()
    params.pop('page', None)

    context = {
        'page_obj': page_obj,
        'total': total_count,
        'filtering': filtering,
        'selected': selected,
        'categories': Category.objects.all(),
        'statuses': Issue.STATUS_CHOICES,
        'base_url': reverse('home'),
        'qs': params.urlencode(),
        'n_total': Issue.objects.count(),
        'n_reported': Issue.objects.filter(status='reported').count(),
        'n_progress': Issue.objects.filter(status='in_progress').count(),
        'n_resolved': Issue.objects.filter(status='resolved').count(),
    }
    return render(request, 'home.html', context)


def command_center(request):
    all_issues = list(Issue.objects.select_related('category', 'department', 'reported_by'))
    critical = sorted([i for i in all_issues if i.status != 'resolved'], key=lambda x: x.priority_score, reverse=True)[:8]
    departments = Department.objects.annotate(
        open_count=Count('issues', filter=~Q(issues__status='resolved')),
        resolved_count=Count('issues', filter=Q(issues__status='resolved')),
    )
    resolved_list = [i for i in all_issues if i.status == 'resolved']
    verified_list = [i for i in resolved_list if i.citizen_verified]
    satisfaction = round((len(verified_list) / len(resolved_list)) * 100) if resolved_list else 100

    return render(request, 'command_center.html', {
        'critical_issues': critical,
        'departments': departments,
        'n_total': len(all_issues),
        'n_open': sum(1 for i in all_issues if i.status != 'resolved'),
        'n_overdue': sum(1 for i in all_issues if i.is_overdue),
        'n_resolved': len(resolved_list),
        'satisfaction': satisfaction,
    })


def smart_classify(request):
    text = request.GET.get('text', '').lower()
    if len(text) < 4:
        return JsonResponse({'matched': False})
    for keywords, cat_name in KEYWORD_RULES:
        if any(k in text for k in keywords):
            cat = Category.objects.filter(name__icontains=cat_name).select_related('department').first()
            if cat:
                return JsonResponse({
                    'matched': True,
                    'category_id': cat.pk,
                    'category_name': cat.name,
                    'department': cat.department.name if cat.department else 'General',
                    'sla_hours': cat.sla_hours,
                })
    return JsonResponse({'matched': False})


def public_issues_api(request):
    issues = Issue.objects.select_related('category', 'department')[:50]
    return JsonResponse({
        'count': len(issues),
        'results': [
            {
                'id': i.pk,
                'title': i.title,
                'category': i.category.name,
                'department': i.department.name if i.department else None,
                'status': i.status,
                'priority_level': i.priority_level,
                'priority_score': i.priority_score,
                'upvotes': i.upvote_count,
                'is_overdue': i.is_overdue,
                'location': i.location,
                'coordinates': {'lat': i.latitude, 'lng': i.longitude},
                'created_at': i.created_at.isoformat(),
            }
            for i in issues
        ]
    })


def issue_poster(request, pk):
    issue = get_object_or_404(Issue.objects.select_related('category', 'department'), pk=pk)
    full_url = request.build_absolute_uri(issue.get_absolute_url())
    return render(request, 'issues/issue_poster.html', {'issue': issue, 'full_url': full_url})


@login_required
def profile(request):
    u = request.user
    reports = Issue.objects.filter(reported_by=u)
    reports_count = reports.count()
    verified_count = reports.filter(citizen_verified=True).count()
    upvotes_received = sum(i.upvote_count for i in reports)
    points = (reports_count * 10) + (upvotes_received * 2) + (verified_count * 15)

    badges = []
    if reports_count >= 1:
        badges.append(('First Responder', 'Submitted your first civic issue report'))
    if upvotes_received >= 3:
        badges.append(('Community Voice', 'Received 3+ neighbor upvotes on your reports'))
    if verified_count >= 1:
        badges.append(('Quality Auditor', 'Verified a completed municipal repair'))
    if points >= 50:
        badges.append(('Civic Champion', 'Reached 50+ Civic Reputation Points'))

    return render(request, 'accounts/profile.html', {
        'points': points,
        'reports_count': reports_count,
        'verified_count': verified_count,
        'upvotes_received': upvotes_received,
        'badges': badges,
    })


def issue_search(request):
    base_qs = Issue.objects.select_related('category', 'department').annotate(
        comment_count=Count('comments', distinct=True),
        num_upvotes=Count('upvotes', distinct=True),
    )
    qs, _, filtering = _filter_issues(request, base_qs)
    total_count = len(qs) if isinstance(qs, list) else qs.count()
    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)

    return render(request, 'issues/_issue_list.html', {
        'page_obj': page_obj,
        'total': total_count,
        'filtering': filtering,
        'base_url': reverse('home'),
        'qs': params.urlencode(),
    })


def leaderboard(request):
    users = User.objects.annotate(
        reports_count=Count('reported_issues', distinct=True),
        verified_count=Count('reported_issues', filter=Q(reported_issues__citizen_verified=True), distinct=True),
        upvotes_received=Count('reported_issues__upvotes', distinct=True),
    )
    board = []
    for u in users:
        points = (u.reports_count * 10) + (u.upvotes_received * 2) + (u.verified_count * 15)
        if points > 0 or u.reports_count > 0:
            if points >= 60:
                badge = 'Civic Champion'
            elif points >= 25:
                badge = 'Neighborhood Watch'
            else:
                badge = 'Active Citizen'
            board.append({
                'user': u,
                'reports': u.reports_count,
                'upvotes': u.upvotes_received,
                'verified': u.verified_count,
                'points': points,
                'badge': badge,
            })
    board.sort(key=lambda x: x['points'], reverse=True)
    return render(request, 'leaderboard.html', {'board': board})


@login_required
def mark_notifications_read(request):
    if request.method == 'POST':
        request.user.notifications.filter(is_read=False).update(is_read=True)
        return JsonResponse({'ok': True})
    return JsonResponse({'error': 'POST required'}, status=405)


def issues_geojson(request):
    issues = Issue.objects.exclude(latitude__isnull=True).exclude(longitude__isnull=True).select_related('category')
    data = [
        {
            'id': i.pk,
            'title': i.title,
            'category': i.category.name,
            'status': i.status,
            'status_display': i.get_status_display(),
            'priority': i.priority_level.upper(),
            'location': i.location,
            'lat': i.latitude,
            'lng': i.longitude,
            'upvotes': i.upvotes.count(),
            'url': i.get_absolute_url(),
        }
        for i in issues
    ]
    return JsonResponse({'issues': data})


def check_duplicates(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 4:
        return JsonResponse({'matches': []})
    words = [w for w in q.split() if len(w) > 3][:4]
    if not words:
        return JsonResponse({'matches': []})
    query = Q()
    for w in words:
        query |= Q(title__icontains=w) | Q(location__icontains=w)
    matches = Issue.objects.exclude(status='resolved').filter(query)[:3]
    return JsonResponse({
        'matches': [
            {
                'id': m.pk,
                'title': m.title,
                'location': m.location,
                'status': m.get_status_display(),
                'upvotes': m.upvotes.count(),
                'url': m.get_absolute_url(),
            }
            for m in matches
        ]
    })


@login_required
def toggle_upvote(request, pk):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    issue = get_object_or_404(Issue, pk=pk)
    if request.user in issue.upvotes.all():
        issue.upvotes.remove(request.user)
        upvoted = False
    else:
        issue.upvotes.add(request.user)
        upvoted = True
    return JsonResponse({'upvoted': upvoted, 'count': issue.upvotes.count()})


@login_required
def verify_resolution(request, pk):
    issue = get_object_or_404(Issue, pk=pk, reported_by=request.user)
    if request.method == 'POST':
        action = request.POST.get('action')
        rating = request.POST.get('rating', '5')
        if action == 'confirm' and issue.status == 'resolved':
            issue.citizen_verified = True
            issue.save()
            StatusUpdate.objects.create(
                issue=issue,
                old_status='resolved',
                new_status='resolved',
                updated_by=request.user,
                remarks=f'Citizen verified completion (Satisfaction Rating: {rating}/5 ★).',
            )
            messages.success(request, f'Resolution verified ({rating}/5 ★)! +15 Civic Reputation points awarded.')
        elif action == 'reopen' and issue.status == 'resolved':
            StatusUpdate.objects.create(
                issue=issue,
                old_status='resolved',
                new_status='in_progress',
                updated_by=request.user,
                remarks='Reopened by original reporter — issue still persists.',
            )
            issue.status = 'in_progress'
            issue.save()
            messages.warning(request, 'Issue reopened and sent back to the department.')
    return redirect(issue.get_absolute_url())


def issue_detail(request, pk):
    issue = get_object_or_404(Issue.objects.select_related('category', 'department', 'reported_by'), pk=pk)
    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect('login')
        comment_form = CommentForm(request.POST)
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.issue = issue
            comment.user = request.user
            comment.save()
            if issue.reported_by != request.user:
                Notification.objects.create(
                    recipient=issue.reported_by,
                    issue=issue,
                    message=f"{request.user.username} commented on your issue #{issue.pk}: {issue.title[:45]}"
                )
            messages.success(request, 'Comment posted.')
            return redirect(issue.get_absolute_url())
    else:
        comment_form = CommentForm()

    can_edit = request.user == issue.reported_by and issue.status == 'reported'
    can_manage = _is_official(request.user)
    user_upvoted = request.user.is_authenticated and issue.upvotes.filter(pk=request.user.pk).exists()

    return render(request, 'issues/issue_detail.html', {
        'issue': issue,
        'updates': issue.updates.select_related('updated_by'),
        'comments': issue.comments.select_related('user'),
        'comment_form': comment_form,
        'can_edit': can_edit,
        'can_manage': can_manage,
        'user_upvoted': user_upvoted,
    })


@login_required
def report_issue(request):
    if request.method == 'POST':
        form = IssueForm(request.POST, request.FILES)
        if form.is_valid():
            issue = form.save(commit=False)
            issue.reported_by = request.user
            issue.save()
            issue.upvotes.add(request.user)
            messages.success(request, 'Issue reported (+10 Civic Points) and routed to the department.')
            return redirect(issue.get_absolute_url())
    else:
        form = IssueForm()
    return render(request, 'issues/issue_form.html', {'form': form, 'mode': 'create'})


@login_required
def edit_issue(request, pk):
    issue = get_object_or_404(Issue, pk=pk, reported_by=request.user)
    if issue.status != 'reported':
        raise PermissionDenied('Cannot edit an issue once work has begun.')
    if request.method == 'POST':
        form = IssueForm(request.POST, request.FILES, instance=issue)
        if form.is_valid():
            form.save()
            messages.success(request, 'Report updated.')
            return redirect(issue.get_absolute_url())
    else:
        form = IssueForm(instance=issue)
    return render(request, 'issues/issue_form.html', {'form': form, 'issue': issue, 'mode': 'edit'})


@login_required
def delete_issue(request, pk):
    issue = get_object_or_404(Issue, pk=pk, reported_by=request.user)
    if request.method == 'POST':
        issue.delete()
        messages.success(request, 'Report deleted.')
        return redirect('home')
    return render(request, 'issues/issue_confirm_delete.html', {'issue': issue})


@login_required
def my_reports(request):
    issues = Issue.objects.filter(reported_by=request.user).select_related(
        'category', 'department'
    ).annotate(comment_count=Count('comments', distinct=True), num_upvotes=Count('upvotes', distinct=True))
    return render(request, 'issues/my_reports.html', {'issues': issues})


def _official_queryset(user):
    qs = Issue.objects.select_related('category', 'department', 'reported_by').annotate(
        num_upvotes=Count('upvotes', distinct=True)
    )
    if user.is_staff:
        return qs, None
    dept = user.departments.first()
    if not dept:
        raise PermissionDenied
    return qs.filter(department=dept), dept


@login_required
def dashboard(request):
    if not _is_official(request.user):
        raise PermissionDenied
    base_qs, dept = _official_queryset(request.user)
    qs, selected, _ = _filter_issues(request, base_qs)

    resolved_issues = [i for i in base_qs if i.status == 'resolved']
    avg_days = (
        round(sum(i.days_open for i in resolved_issues) / len(resolved_issues), 1)
        if resolved_issues else None
    )
    overdue_count = base_qs.exclude(status='resolved').filter(due_at__lt=timezone.now()).count()
    critical_count = sum(1 for i in base_qs if i.priority_level == 'critical')
    hotspots = base_qs.values('location').annotate(n=Count('id')).order_by('-n')[:4]

    total_count = len(qs) if isinstance(qs, list) else qs.count()
    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)

    return render(request, 'dashboard/dashboard.html', {
        'department': dept,
        'departments': Department.objects.all() if request.user.is_staff else None,
        'categories': Category.objects.all(),
        'statuses': Issue.STATUS_CHOICES + [('overdue', 'Overdue (SLA Breached)')],
        'selected': selected,
        'page_obj': page_obj,
        'total': total_count,
        'base_url': reverse('dashboard'),
        'qs': params.urlencode(),
        'hotspots': hotspots,
        'summary': {
            'total': base_qs.count(),
            'reported': base_qs.filter(status='reported').count(),
            'in_progress': base_qs.filter(status='in_progress').count(),
            'resolved': base_qs.filter(status='resolved').count(),
            'overdue': overdue_count,
            'critical': critical_count,
            'avg_days': avg_days,
        },
    })


@login_required
def kanban_board(request):
    if not _is_official(request.user):
        raise PermissionDenied
    base_qs, dept = _official_queryset(request.user)
    return render(request, 'dashboard/kanban.html', {
        'department': dept,
        'reported': base_qs.filter(status='reported'),
        'in_progress': base_qs.filter(status='in_progress'),
        'resolved': base_qs.filter(status='resolved')[:15],
    })


@login_required
def kanban_move(request, pk):
    if not _is_official(request.user) or request.method != 'POST':
        raise PermissionDenied
    base_qs, _ = _official_queryset(request.user)
    issue = get_object_or_404(base_qs, pk=pk)
    data = json.loads(request.body)
    new_status = data.get('status')
    if new_status in dict(Issue.STATUS_CHOICES) and new_status != issue.status:
        StatusUpdate.objects.create(
            issue=issue,
            old_status=issue.status,
            new_status=new_status,
            updated_by=request.user,
            remarks='Moved via Kanban Triage Board.',
        )
        issue.status = new_status
        issue.save()
        Notification.objects.create(
            recipient=issue.reported_by,
            issue=issue,
            message=f"Issue #{issue.pk} moved to '{issue.get_status_display()}'."
        )
    return JsonResponse({'ok': True})


@login_required
def dashboard_stats_api(request):
    if not _is_official(request.user):
        raise PermissionDenied
    base_qs, _ = _official_queryset(request.user)
    today = timezone.now().date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    labels = [d.strftime('%b %d') for d in days]
    reported_series = [base_qs.filter(created_at__date=d).count() for d in days]
    resolved_series = [base_qs.filter(resolved_at__date=d).count() for d in days]

    return JsonResponse({
        'labels': labels,
        'reported': reported_series,
        'resolved': resolved_series,
    })


@login_required
def dashboard_table(request):
    if not _is_official(request.user):
        raise PermissionDenied
    base_qs, _ = _official_queryset(request.user)
    qs, _, _ = _filter_issues(request, base_qs)
    total_count = len(qs) if isinstance(qs, list) else qs.count()
    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'dashboard/_table.html', {
        'page_obj': page_obj,
        'total': total_count,
        'base_url': reverse('dashboard'),
        'qs': params.urlencode(),
    })


@login_required
def manage_issue(request, pk):
    if not _is_official(request.user):
        raise PermissionDenied
    base_qs, _ = _official_queryset(request.user)
    issue = get_object_or_404(base_qs, pk=pk)

    if request.method == 'POST':
        form = StatusUpdateForm(request.POST, request.FILES)
        if form.is_valid():
            new_status = form.cleaned_data['status']
            remarks = form.cleaned_data['remarks']
            res_photo = form.cleaned_data.get('resolution_photo')
            if res_photo:
                issue.resolution_photo = res_photo
            if new_status != issue.status or remarks or res_photo:
                StatusUpdate.objects.create(
                    issue=issue,
                    old_status=issue.status,
                    new_status=new_status,
                    updated_by=request.user,
                    remarks=remarks,
                )
                issue.status = new_status
                issue.save()
                Notification.objects.create(
                    recipient=issue.reported_by,
                    issue=issue,
                    message=f"Issue #{issue.pk} is now '{issue.get_status_display()}'."
                )
                messages.success(request, f'Issue #{issue.pk} updated and citizen notified.')
            return redirect('dashboard')
    else:
        form = StatusUpdateForm(initial={'status': issue.status})

    return render(request, 'dashboard/manage_issue.html', {
        'issue': issue,
        'form': form,
        'updates': issue.updates.select_related('updated_by'),
    })


@login_required
def export_csv(request):
    if not _is_official(request.user):
        raise PermissionDenied
    base_qs, _ = _official_queryset(request.user)
    qs, _, _ = _filter_issues(request, base_qs)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="civicpulse_issues.csv"'
    writer = csv.writer(response)
    writer.writerow(['ID', 'Title', 'Category', 'Priority', 'Score', 'Location', 'Status', 'Upvotes', 'SLA Overdue', 'Created At'])
    for i in qs:
        writer.writerow([
            i.pk, i.title, i.category.name, i.priority_level.upper(), i.priority_score,
            i.location, i.get_status_display(), i.upvotes.count(),
            'YES' if i.is_overdue else 'NO',
            i.created_at.strftime('%Y-%m-%d %H:%M'),
        ])
    return response


@login_required
def export_pdf(request):
    if not _is_official(request.user):
        raise PermissionDenied
    base_qs, dept = _official_queryset(request.user)
    qs, _, _ = _filter_issues(request, base_qs)

    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    p.setFont('Helvetica-Bold', 16)
    p.drawString(40, y, f"CivicPulse Smart Audit Report — {dept.name if dept else 'All Departments'}")
    y -= 22
    p.setFont('Helvetica', 10)
    p.drawString(40, y, f"Generated: {timezone.now().strftime('%Y-%m-%d %H:%M')}")
    y -= 28

    for issue in list(qs)[:40]:
        if y < 60:
            p.showPage()
            y = height - 50
        sla_flag = ' [OVERDUE]' if issue.is_overdue else ''
        p.setFont('Helvetica-Bold', 10)
        p.drawString(40, y, f"#{issue.pk} [{issue.priority_level.upper()} · {issue.get_status_display()}{sla_flag}] {issue.title[:52]}")
        y -= 14
        p.setFont('Helvetica', 9)
        p.drawString(50, y, f"Category: {issue.category.name} | Upvotes: {issue.upvotes.count()} | Location: {issue.location[:40]}")
        y -= 20

    p.save()
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="civicpulse_report.pdf"'
    return response


def register(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Welcome to CivicPulse!')
            return redirect('home')
    else:
        form = RegisterForm()
    return render(request, 'accounts/register.html', {'form': form})


def about(request):
    return render(request, 'about.html')
