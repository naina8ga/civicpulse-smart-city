from pathlib import Path

V8_FILES = {
    "issues/urls.py": """from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('search/', views.issue_search, name='issue_search'),
    path('command-center/', views.command_center, name='command_center'),
    path('predictive-ai/', views.predictive_ai, name='predictive_ai'),
    path('transparency/', views.transparency_ledger, name='transparency_ledger'),
    path('budget-simulator/', views.budget_simulator, name='budget_simulator'),
    path('executive-brief/', views.executive_brief, name='executive_brief'),
    path('api/command-pulse/', views.command_pulse_api, name='command_pulse_api'),
    path('architecture/', views.architecture, name='architecture'),
    path('leaderboard/', views.leaderboard, name='leaderboard'),
    path('profile/', views.profile, name='profile'),
    path('api/v1/issues/', views.public_issues_api, name='public_issues_api'),
    path('api/civicbot/', views.civicbot_api, name='civicbot_api'),
    path('api/issues-geo/', views.issues_geojson, name='issues_geojson'),
    path('api/check-duplicates/', views.check_duplicates, name='check_duplicates'),
    path('api/smart-classify/', views.smart_classify, name='smart_classify'),
    path('api/dashboard-stats/', views.dashboard_stats_api, name='dashboard_stats_api'),
    path('api/notifications/read/', views.mark_notifications_read, name='mark_notifications_read'),
    path('about/', views.about, name='about'),
    path('report/', views.report_issue, name='report_issue'),
    path('my-reports/', views.my_reports, name='my_reports'),
    path('issues/<int:pk>/', views.issue_detail, name='issue_detail'),
    path('issues/<int:pk>/poster/', views.issue_poster, name='issue_poster'),
    path('issues/<int:pk>/upvote/', views.toggle_upvote, name='toggle_upvote'),
    path('issues/<int:pk>/verify/', views.verify_resolution, name='verify_resolution'),
    path('issues/<int:pk>/edit/', views.edit_issue, name='edit_issue'),
    path('issues/<int:pk>/delete/', views.delete_issue, name='delete_issue'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('dashboard/escalate/', views.escalate_overdue, name='escalate_overdue'),
    path('dashboard/simulate-surge/', views.simulate_surge, name='simulate_surge'),
    path('dashboard/broadcast/', views.set_broadcast, name='set_broadcast'),
    path('dashboard/kanban/', views.kanban_board, name='kanban_board'),
    path('dashboard/kanban/move/<int:pk>/', views.kanban_move, name='kanban_move'),
    path('dashboard/table/', views.dashboard_table, name='dashboard_table'),
    path('dashboard/issues/<int:pk>/', views.manage_issue, name='manage_issue'),
    path('dashboard/export/csv/', views.export_csv, name='export_csv'),
    path('dashboard/export/pdf/', views.export_pdf, name='export_pdf'),
    path('accounts/register/', views.register, name='register'),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),
]
""",

    "issues/views.py": """import csv
import json
import random
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


def predictive_ai(request):
    forecasts = []
    for cat in Category.objects.select_related('department'):
        total_cat = Issue.objects.filter(category=cat).count()
        open_cat = Issue.objects.filter(category=cat).exclude(status='resolved').count()
        overdue_cat = Issue.objects.filter(category=cat).exclude(status='resolved').filter(due_at__lt=timezone.now()).count()
        projected_7d = max(2, round(total_cat * 0.45 + open_cat * 0.6))
        risk_score = min(99, round((open_cat * 18) + (overdue_cat * 25) + (cat.severity_weight * 6)))
        if risk_score >= 70:
            risk_label = 'HIGH SURGE RISK'
            advice = f"Pre-position {max(2, open_cat)} field units for {cat.department.name if cat.department else 'Municipal'} preventive sweep."
        elif risk_score >= 40:
            risk_label = 'MODERATE LOAD'
            advice = f"Maintain standard {cat.sla_hours}h SLA rotation and monitor repeat hotspots."
        else:
            risk_label = 'OPTIMAL / STABLE'
            advice = "Current crew capacity exceeds projected 7-day inflow."
        forecasts.append({
            'category': cat.name,
            'department': cat.department.name if cat.department else 'General',
            'open_now': open_cat,
            'projected_7d': projected_7d,
            'risk_score': risk_score,
            'risk_label': risk_label,
            'advice': advice,
        })
    forecasts.sort(key=lambda x: x['risk_score'], reverse=True)
    return render(request, 'predictive_ai.html', {'forecasts': forecasts})


def transparency_ledger(request):
    logs = StatusUpdate.objects.select_related('issue', 'issue__department', 'updated_by').order_by('-updated_at')[:40]
    total_updates = StatusUpdate.objects.count()
    verified_repairs = Issue.objects.filter(citizen_verified=True).count()
    return render(request, 'transparency_ledger.html', {
        'logs': logs,
        'total_updates': total_updates,
        'verified_repairs': verified_repairs,
    })


@login_required
def simulate_surge(request):
    if not _is_official(request.user) or request.method != 'POST':
        raise PermissionDenied
    cats = list(Category.objects.all())
    if not cats:
        messages.error(request, 'Create categories first before running surge simulation.')
        return redirect('dashboard')
    samples = [
        ('Burst main water valve flooding service lane', 'Raj Nagar Extension Sector 12'),
        ('Cluster of 4 dark streetlights near school crossing', 'Kavi Nagar Block C'),
        ('Deep crater pothole slowing morning bus traffic', 'Vaishali Metro Ring Road'),
        ('Overflowing market garbage compactor bin', 'Indirapuram Shipra Mall Road'),
        ('Exposed live junction box on pedestrian footpath', 'Vasundhara Sector 15'),
    ]
    for title, loc in samples:
        cat = random.choice(cats)
        Issue.objects.create(
            title=title,
            description='Simulated smart-city stress-test telemetry ticket.',
            location=loc,
            category=cat,
            reported_by=request.user,
            latitude=round(28.6692 + random.uniform(-0.018, 0.018), 6),
            longitude=round(77.4538 + random.uniform(-0.018, 0.018), 6),
        )
    messages.success(request, 'Simulated 5 live geo-tagged civic incidents across the city!')
    return redirect('dashboard')


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
        reply = f"Estimated municipal repair budget for all {len(open_issues)} open tickets is ₹{est:,}. Open Budget AI for crew projections!"
    elif 'predict' in q or 'forecast' in q or 'risk' in q:
        reply = f"Predictive AI tracks {len(open_issues)} open incidents. Visit /predictive-ai/ to see 7-day surge forecasts by department!"
    elif 'point' in q or 'badge' in q or 'leaderboard' in q:
        reply = "You earn +10 pts per report, +2 pts per neighbor upvote received, and +15 pts when you confirm a repair is fixed!"
    else:
        resolved_count = sum(1 for i in all_issues if i.status == 'resolved')
        reply = (
            f"CivicPulse Live Status: {len(all_issues)} total reports, {len(open_issues)} active, "
            f"{len(overdue)} overdue, and {resolved_count} resolved. Ask about 'overdue', 'top priority', 'budget cost', or '7-day forecast'!"
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
""",

    "templates/base.html": """{% load static %}
<!doctype html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}CivicPulse — Sovereign Smart City OS{% endblock %}</title>
  <link rel="manifest" href="{% static 'manifest.json' %}">
  <link rel="icon" href="{% static 'icon.svg' %}" type="image/svg+xml">
  <meta name="theme-color" content="#0f4c81">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin="">
  <link rel="stylesheet" href="{% static 'css/style.css' %}">
  <script>
    const savedTheme = localStorage.getItem('cp_theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
  </script>
  {% block extra_head %}{% endblock %}
</head>
<body>
  <a class="skip" href="#main">Skip to content</a>

  {% if emergency_broadcast %}
    <div class="alert-ticker">
      <span>🚨 MUNICIPAL EMERGENCY BROADCAST: {{ emergency_broadcast }}</span>
    </div>
  {% endif %}

  <header class="topbar">
    <div class="wrap bar">
      <a class="brand" href="{% url 'home' %}">
        <span class="brand-pulse" aria-hidden="true"></span>
        <span>Civic<strong>Pulse</strong></span>
      </a>

      <nav class="nav" aria-label="Primary">
        <a href="{% url 'home' %}" {% if request.resolver_match.url_name == 'home' %}aria-current="page"{% endif %}>Issues</a>
        <a href="{% url 'report_issue' %}" {% if request.resolver_match.url_name == 'report_issue' %}aria-current="page"{% endif %}>+ Report</a>
        <a href="{% url 'command_center' %}" {% if request.resolver_match.url_name == 'command_center' %}aria-current="page"{% endif %}>Command Center</a>
        <a href="{% url 'predictive_ai' %}" {% if request.resolver_match.url_name == 'predictive_ai' %}aria-current="page"{% endif %}>Predictive AI</a>
        <a href="{% url 'budget_simulator' %}" {% if request.resolver_match.url_name == 'budget_simulator' %}aria-current="page"{% endif %}>Budget AI</a>
        <a href="{% url 'transparency_ledger' %}" {% if request.resolver_match.url_name == 'transparency_ledger' %}aria-current="page"{% endif %}>Audit Log</a>
        <a href="{% url 'leaderboard' %}" {% if request.resolver_match.url_name == 'leaderboard' %}aria-current="page"{% endif %}>Leaderboard</a>
        {% if is_official %}
          <a href="{% url 'dashboard' %}" class="nav-official" {% if 'dashboard' in request.path %}aria-current="page"{% endif %}>Department</a>
        {% endif %}
      </nav>

      <div class="account">
        <button type="button" id="theme-toggle" class="icon-btn" title="Toggle Dark/Light Theme" aria-label="Toggle Theme">🌓</button>

        {% if user.is_authenticated %}
          <div class="notif-wrap">
            <button type="button" class="icon-btn" id="notif-toggle" aria-label="Notifications">
              🔔 {% if unread_count %}<span class="notif-badge" id="notif-badge">{{ unread_count }}</span>{% endif %}
            </button>
            <div class="notif-menu" id="notif-menu" style="display:none;">
              <div class="notif-head">
                <strong>Notifications</strong>
                {% if unread_count %}
                  <button type="button" class="link-btn" id="mark-read-btn" data-url="{% url 'mark_notifications_read' %}" data-csrf="{{ csrf_token }}">Mark all read</button>
                {% endif %}
              </div>
              {% for n in unread_notifications %}
                <a class="notif-item" href="{% if n.issue %}{{ n.issue.get_absolute_url }}{% else %}#{% endif %}">{{ n.message }}</a>
              {% empty %}
                <div class="notif-empty">You're all caught up!</div>
              {% endfor %}
            </div>
          </div>

          <a class="user-pill" href="{% url 'profile' %}" title="View Civic ID & Badges">
            <span class="avatar-dot">{{ user.username|slice:":1"|upper }}</span>
            <span>{{ user.first_name|default:user.username }}</span>
          </a>
          <form method="post" action="{% url 'logout' %}">
            {% csrf_token %}
            <button type="submit" class="link-btn">Log out</button>
          </form>
        {% else %}
          <a href="{% url 'login' %}" class="btn btn--small btn--ghost">Log in</a>
          <a class="btn btn--small" href="{% url 'register' %}">Join Free</a>
        {% endif %}
      </div>
    </div>
  </header>

  {% if messages %}
    <div class="wrap messages" role="status">
      {% for message in messages %}
        <div class="notice notice--{{ message.tags }}">{{ message }}</div>
      {% endfor %}
    </div>
  {% endif %}

  <main id="main" class="wrap">
    {% block content %}{% endblock %}
  </main>

  <div id="civicbot-widget" data-api-url="{% url 'civicbot_api' %}" style="position:fixed; bottom:24px; right:24px; z-index:999;">
    <div id="civicbot-box" class="bot-window" style="display:none;">
      <div class="bot-header">
        <span>✨ CivicBot AI Assistant</span>
        <button type="button" id="civicbot-close" style="background:none; border:none; color:#fff; cursor:pointer; font-size:1rem;">✕</button>
      </div>
      <div id="civicbot-log" class="bot-log">
        <div class="bot-msg bot-msg--ai">
          Hello! Ask me live questions like <strong>"overdue SLAs"</strong>, <strong>"top priority"</strong>, <strong>"budget cost"</strong>, or <strong>"7-day forecast"</strong>.
        </div>
      </div>
      <form id="civicbot-form" class="bot-form">
        <input type="text" id="civicbot-input" placeholder="Ask anything about city status...">
        <button type="submit">Send</button>
      </form>
    </div>
    <button type="button" id="civicbot-toggle" class="btn bot-fab">💬 CivicBot AI</button>
  </div>

  <footer class="footer">
    <div class="wrap footer-inner">
      <span><strong>CivicPulse v8</strong> — Sovereign Smart-City Governance, Predictive AI &amp; Digital Twin OS</span>
      <span><a href="{% url 'executive_brief' %}">Executive Brief</a> · <a href="{% url 'public_issues_api' %}" target="_blank">REST API</a> · <a href="{% url 'architecture' %}">Architecture</a></span>
    </div>
  </footer>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
  <script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
  <script src="{% static 'js/main.js' %}" defer></script>
  <script>
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register("{% static 'sw.js' %}").catch(() => {});
    }
  </script>
  {% block extra_scripts %}{% endblock %}
</body>
</html>
""",

    "templates/home.html": """{% extends "base.html" %}
{% block title %}CivicPulse — Smart City Issue & SLA Tracker{% endblock %}

{% block content %}
<section class="hero-card">
  <div class="hero-left">
    <span class="hero-eyebrow">SMART MUNICIPAL GOVERNANCE · DIGITAL TWIN</span>
    <h1>Report neighborhood issues. Track live municipal action.</h1>
    <p>Geo-tagged reporting with Vision AI photo diagnostics, live SLA countdowns, thermal heatmaps, and transparent before-and-after verification.</p>
    <div class="hero-actions">
      <a class="btn" href="{% url 'report_issue' %}">+ Report an Issue</a>
      <button type="button" class="btn btn--ghost" id="toggle-map-btn" data-geo-url="{% url 'issues_geojson' %}">🗺️ Live Map &amp; Heatmap</button>
      <a class="btn btn--ghost" href="{% url 'command_center' %}">📡 Command Center</a>
    </div>
  </div>

  <div class="hero-right">
    <div class="stat-headline">
      <span class="stat-big">{{ n_total }}</span>
      <span class="stat-sub">Total Civic Reports Logged</span>
    </div>
    <div class="progress-track" aria-hidden="true">
      {% if n_total %}
        <span class="prog-seg prog-seg--reported" style="width:{% widthratio n_reported n_total 100 %}%"></span>
        <span class="prog-seg prog-seg--in_progress" style="width:{% widthratio n_progress n_total 100 %}%"></span>
        <span class="prog-seg prog-seg--resolved" style="width:{% widthratio n_resolved n_total 100 %}%"></span>
      {% endif %}
    </div>
    <ul class="legend-grid">
      <li><span class="dot dot--reported"></span>Reported <strong>{{ n_reported }}</strong></li>
      <li><span class="dot dot--in_progress"></span>In Progress <strong>{{ n_progress }}</strong></li>
      <li><span class="dot dot--resolved"></span>Resolved <strong>{{ n_resolved }}</strong></li>
    </ul>
  </div>
</section>

<section id="city-map-wrap" class="map-panel" style="display:none;">
  <div class="map-toolbar">
    <div>
      <strong>Interactive City Incident Radar &amp; Thermal Heatmap</strong>
      <span class="muted" id="radar-status" style="font-size:0.82rem; display:block;">Click any marker to inspect status &amp; upvotes, or scan a 2 km proximity radius.</span>
    </div>
    <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
      <button type="button" class="btn btn--small btn--ghost" id="scan-radius-btn">📡 Scan Within 2 km</button>
      <button type="button" class="btn btn--small btn--ghost" id="toggle-sat-btn">🛰️ Satellite View</button>
      <button type="button" class="btn btn--small" id="toggle-heat-btn">🔥 Toggle Density Heatmap</button>
    </div>
  </div>
  <div id="city-map" style="height:410px; width:100%; border-radius:8px; border:1px solid var(--border);"></div>
</section>

<form class="filters filters--home" method="get" action="{% url 'home' %}"
      data-live-filter data-endpoint="{% url 'issue_search' %}" data-target="#issue-results">
  <div class="field field--search">
    <label for="f-q">Live Search</label>
    <input id="f-q" type="search" name="q" value="{{ selected.q }}" placeholder="Search by keyword, street, landmark...">
  </div>
  <div class="field">
    <label for="f-cat">Category</label>
    <select id="f-cat" name="category">
      <option value="">All Categories</option>
      {% for c in categories %}
        <option value="{{ c.pk }}" {% if selected.category == c.pk|stringformat:"s" %}selected{% endif %}>{{ c.name }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="field">
    <label for="f-status">Status</label>
    <select id="f-status" name="status">
      <option value="">All Statuses</option>
      {% for val, label in statuses %}
        <option value="{{ val }}" {% if selected.status == val %}selected{% endif %}>{{ label }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="field">
    <label for="f-sort">Sort Order</label>
    <select id="f-sort" name="sort">
      <option value="recent" {% if selected.sort == 'recent' %}selected{% endif %}>Newest First</option>
      <option value="priority" {% if selected.sort == 'priority' %}selected{% endif %}>Highest Urgency</option>
      <option value="upvotes" {% if selected.sort == 'upvotes' %}selected{% endif %}>Most Upvoted</option>
    </select>
  </div>
</form>

<div id="issue-results" aria-live="polite">
  {% include "issues/_issue_list.html" %}
</div>
{% endblock %}
""",

    "templates/predictive_ai.html": """{% extends "base.html" %}
{% block title %}7-Day Predictive AI Outbreak Forecaster — CivicPulse{% endblock %}

{% block content %}
<div class="page-head">
  <div>
    <span class="hero-eyebrow">PREDICTIVE URBAN ANALYTICS ENGINE</span>
    <h1>7-Day Civic Incident Surge &amp; SLA Risk Forecast</h1>
    <p class="muted">Projects next week's ticket inflow and flags high-risk municipal departments for preventive dispatch.</p>
  </div>
  <a href="{% url 'budget_simulator' %}" class="btn btn--small">Open Budget AI →</a>
</div>

<div class="cards-stack">
  {% for f in forecasts %}
    <article class="issue-card">
      <div class="issue-card-main">
        <div class="issue-card-top">
          <span class="cat-pill">{{ f.department }}</span>
          {% if f.risk_score >= 70 %}
            <span class="badge badge--overdue">{{ f.risk_label }} · {{ f.risk_score }}/100</span>
          {% elif f.risk_score >= 40 %}
            <span class="badge badge--high">{{ f.risk_label }} · {{ f.risk_score }}/100</span>
          {% else %}
            <span class="badge badge--verified">{{ f.risk_label }} · {{ f.risk_score }}/100</span>
          {% endif %}
        </div>
        <h3 style="margin-bottom:0.25rem;">{{ f.category }} — Projected 7-Day Inflow: +{{ f.projected_7d }} Tickets</h3>
        <p class="muted" style="font-size:0.9rem;"><strong>AI Dispatch Recommendation:</strong> {{ f.advice }}</p>
      </div>
      <div class="issue-card-right">
        <span class="upvote-pill">{{ f.open_now }} Active Now</span>
      </div>
    </article>
  {% endfor %}
</div>
{% endblock %}
""",

    "templates/transparency_ledger.html": """{% extends "base.html" %}
{% block title %}Public Transparency & Immutable Audit Ledger — CivicPulse{% endblock %}

{% block content %}
<div class="page-head">
  <div>
    <span class="hero-eyebrow">OPEN GOVERNMENT ACCOUNTABILITY</span>
    <h1>Public Civic Audit &amp; SLA Transition Ledger</h1>
    <p class="muted">Every department status change, escalation, and citizen verification is logged publicly in real time.</p>
  </div>
  <div style="display:flex; gap:0.75rem;">
    <span class="upvote-pill">📋 {{ total_updates }} Audit Events</span>
    <span class="upvote-pill">✓ {{ verified_repairs }} Citizen Verified</span>
  </div>
</div>

<div class="table-wrap">
  <table class="data">
    <thead>
      <tr>
        <th>Timestamp</th>
        <th>Issue</th>
        <th>Department</th>
        <th>Transition</th>
        <th>Official / Citizen</th>
        <th>Audit Remarks</th>
      </tr>
    </thead>
    <tbody>
      {% for log in logs %}
        <tr>
          <td class="muted" style="white-space:nowrap;">{{ log.updated_at|date:"M j, H:i" }}</td>
          <td><a href="{{ log.issue.get_absolute_url }}"><strong>#{{ log.issue.pk }} {{ log.issue.title|truncatechars:38 }}</strong></a></td>
          <td>{{ log.issue.department.name|default:"General" }}</td>
          <td><span class="cat-pill">{{ log.get_old_status_display }} → {{ log.get_new_status_display }}</span></td>
          <td>{{ log.updated_by.username|default:"System" }}</td>
          <td>{{ log.remarks|default:"Status updated" }}</td>
        </tr>
      {% empty %}
        <tr><td colspan="6">No audit events recorded yet.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
""",

    "templates/dashboard/dashboard.html": """{% extends "base.html" %}
{% block title %}Department Dashboard — CivicPulse{% endblock %}

{% block extra_head %}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
{% endblock %}

{% block content %}
<div class="page-head">
  <div>
    <h1>{% if department %}{{ department.name }}{% else %}All Departments{% endif %} — Command Dashboard</h1>
    <p class="muted">SLA-monitored queue ranked by urgency score, citizen upvotes, and elapsed resolution window.</p>
  </div>
  <div style="display:flex; gap:0.5rem; flex-wrap:wrap; align-items:center;">
    <form method="post" action="{% url 'simulate_surge' %}">
      {% csrf_token %}
      <button type="submit" class="btn btn--small btn--ghost" title="Inject 5 realistic live incidents for demo">⚡ Simulate Live Surge</button>
    </form>
    <form method="post" action="{% url 'escalate_overdue' %}">
      {% csrf_token %}
      <button type="submit" class="btn btn--small btn--danger-solid">🚨 Auto-Escalate Overdue ({{ summary.overdue }})</button>
    </form>
    <a class="btn btn--small btn--ghost" href="{% url 'kanban_board' %}">Kanban Board</a>
    <a class="btn btn--small btn--ghost" data-export data-base="{% url 'export_csv' %}" href="{% url 'export_csv' %}{% if qs %}?{{ qs }}{% endif %}">CSV</a>
    <a class="btn btn--small btn--ghost" data-export data-base="{% url 'export_pdf' %}" href="{% url 'export_pdf' %}{% if qs %}?{{ qs }}{% endif %}">PDF</a>
  </div>
</div>

<form method="post" action="{% url 'set_broadcast' %}" style="display:flex; gap:0.5rem; margin-bottom:1.25rem; background:var(--surface); padding:0.75rem; border:1px solid var(--border); border-radius:var(--radius);">
  {% csrf_token %}
  <input type="text" name="broadcast_msg" value="{{ emergency_broadcast }}" placeholder="Broadcast citywide emergency alert ticker (leave empty to clear)..."
         style="flex:1; padding:0.45rem 0.7rem; border:1px solid var(--border); border-radius:6px; background:var(--surface-alt); color:var(--text);">
  <button type="submit" class="btn btn--small">Publish City Alert</button>
</form>

<section class="kpis">
  <div class="kpi"><span class="kpi-n">{{ summary.total }}</span><span class="kpi-l">Assigned</span></div>
  <div class="kpi"><span class="kpi-n">{{ summary.reported }}</span><span class="kpi-l">Awaiting Action</span></div>
  <div class="kpi"><span class="kpi-n">{{ summary.in_progress }}</span><span class="kpi-l">In Progress</span></div>
  <div class="kpi"><span class="kpi-n">{{ summary.resolved }}</span><span class="kpi-l">Resolved</span></div>
  <div class="kpi" style="border-color:#fca5a5;"><span class="kpi-n" style="color:var(--danger);">{{ summary.overdue }}</span><span class="kpi-l">Overdue (SLA)</span></div>
  <div class="kpi"><span class="kpi-n">{% if summary.avg_days is not None %}{{ summary.avg_days }}d{% else %}—{% endif %}</span><span class="kpi-l">Avg Resolution</span></div>
</section>

<section class="charts-grid" data-stats-url="{% url 'dashboard_stats_api' %}">
  <div class="bars" style="margin-bottom:0;">
    <h2>7-Day Report vs. Resolution Velocity</h2>
    <canvas id="trendChart" height="110"></canvas>
  </div>
  <div class="bars" style="margin-bottom:0;">
    <h2>Top Location Hotspots</h2>
    <ul style="list-style:none; margin-top:0.75rem;">
      {% for h in hotspots %}
        <li style="display:flex; justify-content:space-between; padding:0.45rem 0; border-bottom:1px solid var(--border); font-size:0.9rem;">
          <span>{{ h.location|truncatechars:34 }}</span>
          <strong>{{ h.n }} report{{ h.n|pluralize }}</strong>
        </li>
      {% empty %}
        <li class="muted">No hotspot data yet.</li>
      {% endfor %}
    </ul>
  </div>
</section>

<form class="filters filters--dash" method="get" action="{% url 'dashboard' %}"
      data-live-filter data-endpoint="{% url 'dashboard_table' %}" data-target="#dashboard-table">
  <div class="field">
    <label for="d-q">Search</label>
    <input id="d-q" type="search" name="q" value="{{ selected.q }}" placeholder="Title, location...">
  </div>
  {% if departments %}
    <div class="field">
      <label for="d-dept">Department</label>
      <select id="d-dept" name="department">
        <option value="">All</option>
        {% for d in departments %}
          <option value="{{ d.pk }}" {% if selected.department == d.pk|stringformat:"s" %}selected{% endif %}>{{ d.name }}</option>
        {% endfor %}
      </select>
    </div>
  {% endif %}
  <div class="field">
    <label for="d-cat">Category</label>
    <select id="d-cat" name="category">
      <option value="">All</option>
      {% for c in categories %}
        <option value="{{ c.pk }}" {% if selected.category == c.pk|stringformat:"s" %}selected{% endif %}>{{ c.name }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="field">
    <label for="d-status">Status / SLA</label>
    <select id="d-status" name="status">
      <option value="">All</option>
      {% for val, label in statuses %}
        <option value="{{ val }}" {% if selected.status == val %}selected{% endif %}>{{ label }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="field">
    <label for="d-sort">Sort by</label>
    <select id="d-sort" name="sort">
      <option value="priority" {% if selected.sort == 'priority' %}selected{% endif %}>Urgency Score</option>
      <option value="recent" {% if selected.sort == 'recent' %}selected{% endif %}>Newest first</option>
      <option value="upvotes" {% if selected.sort == 'upvotes' %}selected{% endif %}>Most upvoted</option>
    </select>
  </div>
</form>

<div id="dashboard-table" aria-live="polite">
  {% include "dashboard/_table.html" %}
</div>
{% endblock %}
""",

    "issues/tests.py": """from datetime import timedelta
from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from .models import Category, Department, Issue


class CivicPulseSovereignTests(TestCase):
    def setUp(self):
        self.citizen = User.objects.create_user('test_citizen', 'c@test.com', 'pass1234')
        self.official = User.objects.create_user('test_official', 'o@test.com', 'pass1234')
        self.dept = Department.objects.create(name='Roads & Bridges', contact_email='roads@city.gov')
        self.dept.officials.add(self.official)
        self.cat = Category.objects.create(
            name='Pothole', department=self.dept, sla_hours=24, severity_weight=4
        )
        self.issue = Issue.objects.create(
            title='Deep pothole near main metro gate',
            description='Causing traffic congestion and two-wheeler accidents.',
            location='Main Metro Gate, Sector 18',
            category=self.cat,
            reported_by=self.citizen,
            latitude=28.6692,
            longitude=77.4538,
        )

    def test_auto_routing_and_sla_deadline(self):
        self.assertEqual(self.issue.department, self.dept)
        self.assertIsNotNone(self.issue.due_at)
        self.assertFalse(self.issue.is_overdue)

    def test_sla_breach_detection(self):
        self.issue.due_at = timezone.now() - timedelta(hours=2)
        self.issue.save()
        self.assertTrue(self.issue.is_overdue)
        self.assertEqual(self.issue.priority_level, 'critical')

    def test_priority_score_increases_with_upvotes(self):
        base_score = self.issue.priority_score
        self.issue.upvotes.add(self.citizen)
        self.assertGreater(self.issue.priority_score, base_score)

    def test_ai_smart_classify_endpoint(self):
        client = Client()
        res = client.get(reverse('smart_classify'), {'text': 'Huge asphalt pothole on highway'})
        data = res.json()
        self.assertTrue(data['matched'])
        self.assertEqual(data['category_name'], 'Pothole')

    def test_duplicate_detection_endpoint(self):
        client = Client()
        res = client.get(reverse('check_duplicates'), {'q': 'pothole metro gate'})
        self.assertEqual(len(res.json()['matches']), 1)

    def test_civicbot_nlp_endpoint(self):
        client = Client()
        res = client.get(reverse('civicbot_api'), {'q': 'top priority'})
        self.assertIn('Deep pothole', res.json()['reply'])

    def test_public_rest_api(self):
        client = Client()
        res = client.get(reverse('public_issues_api'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['count'], 1)

    def test_predictive_ai_and_transparency_ledger(self):
        client = Client()
        self.assertEqual(client.get(reverse('predictive_ai')).status_code, 200)
        self.assertEqual(client.get(reverse('transparency_ledger')).status_code, 200)

    def test_budget_simulator_and_executive_brief(self):
        client = Client()
        self.assertEqual(client.get(reverse('budget_simulator')).status_code, 200)
        self.assertEqual(client.get(reverse('executive_brief')).status_code, 200)

    def test_command_center_and_pulse_api(self):
        client = Client()
        self.assertEqual(client.get(reverse('command_center')).status_code, 200)
        self.assertEqual(client.get(reverse('command_pulse_api')).json()['total'], 1)

    def test_rbac_blocks_citizen_from_dashboard(self):
        client = Client()
        client.force_login(self.citizen)
        res = client.get(reverse('dashboard'))
        self.assertEqual(res.status_code, 403)

    def test_official_can_access_dashboard_kanban_and_simulate(self):
        client = Client()
        client.force_login(self.official)
        self.assertEqual(client.get(reverse('dashboard')).status_code, 200)
        self.assertEqual(client.get(reverse('kanban_board')).status_code, 200)
        res = client.post(reverse('simulate_surge'))
        self.assertEqual(res.status_code, 302)
        self.assertEqual(Issue.objects.count(), 6)
""",

    "static/js/main.js": """const STREET_TILE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}';
const SAT_TILE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

document.addEventListener('DOMContentLoaded', () => {
  // 0. Dark / Light Theme Switcher
  const themeBtn = document.getElementById('theme-toggle');
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const curr = document.documentElement.getAttribute('data-theme');
      const next = curr === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('cp_theme', next);
    });
  }

  // 00. Command Center 15s Real-Time Auto-Sync
  const cmdRoot = document.getElementById('cmd-root');
  if (cmdRoot) {
    let lastKnownTotal = parseInt(document.getElementById('pulse-total')?.textContent || '0', 10);
    setInterval(() => {
      fetch(cmdRoot.dataset.pulseUrl)
        .then((r) => r.json())
        .then((data) => {
          document.getElementById('pulse-total').textContent = data.total;
          document.getElementById('pulse-open').textContent = data.open;
          document.getElementById('pulse-overdue').textContent = data.overdue;
          document.getElementById('pulse-resolved').textContent = data.resolved;
          if (data.total > lastKnownTotal) {
            const toast = document.getElementById('cmd-live-toast');
            if (toast) {
              toast.textContent = `NEW LIVE INCIDENT DETECTED: #${data.latest_id} — ${data.latest_title}`;
              toast.style.display = 'block';
            }
            lastKnownTotal = data.total;
          }
        });
    }, 15000);
  }

  // 0A. Floating CivicBot Assistant
  const botWidget = document.getElementById('civicbot-widget');
  const botBox = document.getElementById('civicbot-box');
  const botToggle = document.getElementById('civicbot-toggle');
  const botClose = document.getElementById('civicbot-close');
  const botForm = document.getElementById('civicbot-form');
  const botInput = document.getElementById('civicbot-input');
  const botLog = document.getElementById('civicbot-log');

  if (botToggle && botBox) {
    botToggle.addEventListener('click', () => {
      botBox.style.display = botBox.style.display === 'none' ? 'block' : 'none';
    });
    if (botClose) botClose.addEventListener('click', () => { botBox.style.display = 'none'; });
    if (botForm) {
      botForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const q = botInput.value.trim();
        if (!q) return;
        botLog.innerHTML += `<div style="text-align:right; margin-bottom:0.5rem;"><span style="background:var(--primary); color:#fff; padding:0.45rem 0.75rem; border-radius:8px; display:inline-block;">${q}</span></div>`;
        botInput.value = '';
        fetch(`${botWidget.dataset.apiUrl}?q=${encodeURIComponent(q)}`)
          .then((r) => r.json())
          .then((data) => {
            botLog.innerHTML += `<div class="bot-msg bot-msg--ai">${data.reply}</div>`;
            botLog.scrollTop = botLog.scrollHeight;
          });
      });
    }
  }

  // 0B. Notification Dropdown
  const notifToggle = document.getElementById('notif-toggle');
  const notifMenu = document.getElementById('notif-menu');
  if (notifToggle && notifMenu) {
    notifToggle.addEventListener('click', () => {
      notifMenu.style.display = notifMenu.style.display === 'none' ? 'block' : 'none';
    });
    const markBtn = document.getElementById('mark-read-btn');
    if (markBtn) {
      markBtn.addEventListener('click', () => {
        fetch(markBtn.dataset.url, {
          method: 'POST',
          headers: { 'X-CSRFToken': markBtn.dataset.csrf }
        }).then(() => {
          const badge = document.getElementById('notif-badge');
          if (badge) badge.remove();
          markBtn.remove();
        });
      });
    }
  }

  // 1. Live AJAX Search & Filter
  const filterForm = document.querySelector('[data-live-filter]');
  if (filterForm) {
    const endpoint = filterForm.dataset.endpoint;
    const target = document.querySelector(filterForm.dataset.target);
    const exportLinks = document.querySelectorAll('[data-export]');
    let debounceTimer;

    const syncExportLinks = (qs) => {
      exportLinks.forEach((link) => {
        const base = link.dataset.base;
        link.href = qs ? `${base}?${qs}` : base;
      });
    };

    const fetchResults = (urlOverride = null) => {
      const params = new URLSearchParams(new FormData(filterForm));
      const qs = params.toString();
      syncExportLinks(qs);

      fetch(urlOverride || `${endpoint}?${qs}`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then((r) => r.text())
        .then((html) => { if (target) target.innerHTML = html; });
    };

    filterForm.addEventListener('input', (e) => {
      if (e.target.type === 'search') {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => fetchResults(), 250);
      } else {
        fetchResults();
      }
    });
    filterForm.addEventListener('change', () => fetchResults());
    filterForm.addEventListener('submit', (e) => { e.preventDefault(); fetchResults(); });

    if (target) {
      target.addEventListener('click', (e) => {
        const link = e.target.closest('.pager a');
        if (link) {
          e.preventDefault();
          fetchResults(`${endpoint}${new URL(link.href).search}`);
        }
      });
    }
  }

  // 2. Homepage Map, Satellite Switcher, Thermal Heatmap & 2km Proximity Radar
  const initLiveMap = (elId, geoUrl, onReady = null) => {
    const el = document.getElementById(elId);
    if (!el || !window.L) return null;
    const map = L.map(elId).setView([28.6692, 77.4538], 13);
    const streetLayer = L.tileLayer(STREET_TILE, { attribution: 'Tiles &copy; Esri' }).addTo(map);
    const satLayer = L.tileLayer(SAT_TILE, { attribution: 'Tiles &copy; Esri' });

    fetch(geoUrl)
      .then((r) => r.json())
      .then((data) => {
        const colors = { reported: '#d97706', in_progress: '#2563eb', resolved: '#16a34a' };
        const heatPoints = [];
        const bounds = [];

        data.issues.forEach((item) => {
          heatPoints.push([item.lat, item.lng, 1.0]);
          bounds.push([item.lat, item.lng]);
          L.circleMarker([item.lat, item.lng], {
            radius: 9,
            fillColor: colors[item.status] || '#0f4c81',
            color: '#fff',
            weight: 2,
            fillOpacity: 0.92
          })
            .addTo(map)
            .bindPopup(`<strong><a href="${item.url}">${item.title}</a></strong><br>${item.category} · ${item.status_display} [${item.priority}]<br>▲ ${item.upvotes} upvotes`);
        });

        if (bounds.length > 0) {
          map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
        }
        if (onReady) onReady(map, heatPoints, streetLayer, satLayer, data.issues);
      });
    return map;
  };

  const cmdMapEl = document.getElementById('cmd-map');
  if (cmdMapEl) initLiveMap('cmd-map', cmdMapEl.dataset.geoUrl);

  const mapBtn = document.getElementById('toggle-map-btn');
  const heatBtn = document.getElementById('toggle-heat-btn');
  const satBtn = document.getElementById('toggle-sat-btn');
  const radiusBtn = document.getElementById('scan-radius-btn');
  const radarStatus = document.getElementById('radar-status');
  const mapWrap = document.getElementById('city-map-wrap');
  let cityMap = null;
  let heatLayer = null;
  let radiusCircle = null;
  let loadedIssues = [];
  let heatActive = false;
  let satActive = false;
  let streetRef = null;
  let satRef = null;

  if (mapBtn && mapWrap) {
    mapBtn.addEventListener('click', () => {
      const hidden = mapWrap.style.display === 'none';
      mapWrap.style.display = hidden ? 'block' : 'none';
      mapBtn.textContent = hidden ? '✕ Hide Map' : '🗺️ Live Map & Heatmap';
      if (hidden && !cityMap) {
        setTimeout(() => {
          cityMap = initLiveMap('city-map', mapBtn.dataset.geoUrl, (m, pts, st, sa, issues) => {
            streetRef = st;
            satRef = sa;
            loadedIssues = issues;
            if (window.L && window.L.heatLayer) {
              heatLayer = L.heatLayer(pts, { radius: 32, blur: 20, maxZoom: 15 });
            }
          });
        }, 50);
      } else if (hidden && cityMap) {
        setTimeout(() => cityMap.invalidateSize(), 100);
      }
    });

    if (radiusBtn) {
      radiusBtn.addEventListener('click', () => {
        if (!cityMap) return;
        const center = cityMap.getCenter();
        if (radiusCircle) cityMap.removeLayer(radiusCircle);
        radiusCircle = L.circle(center, {
          radius: 2000,
          color: '#0ea5e9',
          fillColor: '#0ea5e9',
          fillOpacity: 0.12
        }).addTo(cityMap);
        const inside = loadedIssues.filter((i) => center.distanceTo([i.lat, i.lng]) <= 2000).length;
        if (radarStatus) {
          radarStatus.textContent = `📡 Proximity Scan Active: ${inside} civic issue(s) detected within 2.0 km of map center.`;
        }
      });
    }

    if (heatBtn) {
      heatBtn.addEventListener('click', () => {
        if (!cityMap || !heatLayer) return;
        if (heatActive) {
          cityMap.removeLayer(heatLayer);
          heatBtn.textContent = '🔥 Toggle Density Heatmap';
        } else {
          heatLayer.addTo(cityMap);
          heatBtn.textContent = '❄️ Hide Density Heatmap';
        }
        heatActive = !heatActive;
      });
    }

    if (satBtn) {
      satBtn.addEventListener('click', () => {
        if (!cityMap || !streetRef || !satRef) return;
        if (satActive) {
          cityMap.removeLayer(satRef);
          streetRef.addTo(cityMap);
          satBtn.textContent = '🛰️ Satellite View';
        } else {
          cityMap.removeLayer(streetRef);
          satRef.addTo(cityMap);
          satBtn.textContent = '🗺️ Street Map';
        }
        satActive = !satActive;
      });
    }
  }

  // 3. Report Form Pin Picker + Voice Dictation + Vision AI + Smart Auto-Classify
  const photoInput = document.getElementById('id_photo');
  const photoPreview = document.getElementById('photo-preview');
  const visionBanner = document.getElementById('vision-ai-banner');
  if (photoInput && photoPreview) {
    photoInput.addEventListener('change', () => {
      const file = photoInput.files[0];
      if (!file) return;
      const url = URL.createObjectURL(file);
      photoPreview.src = url;
      photoPreview.style.display = 'block';

      photoPreview.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = 48;
        canvas.height = 48;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(photoPreview, 0, 0, 48, 48);
        const pixels = ctx.getImageData(0, 0, 48, 48).data;
        let lumSum = 0;
        for (let i = 0; i < pixels.length; i += 4) {
          lumSum += 0.299 * pixels[i] + 0.587 * pixels[i + 1] + 0.114 * pixels[i + 2];
        }
        const avgBrightness = Math.round(lumSum / (48 * 48));
        if (visionBanner) {
          const condition = avgBrightness < 75
            ? 'Low-Light / Nighttime Scene Detected (High Visibility Hazard Flag)'
            : 'Clear Daylight Field Evidence Verified';
          visionBanner.innerHTML = `<strong>👁️ Vision AI Photo Diagnostic:</strong> ${condition} · Resolution &amp; Format Validated (${(file.size / 1024).toFixed(0)} KB).`;
          visionBanner.style.display = 'block';
        }
      };
    });
  }

  const pickerEl = document.getElementById('picker-map');
  if (pickerEl && window.L) {
    const latInput = document.getElementById('id_latitude');
    const lngInput = document.getElementById('id_longitude');
    const locInput = document.getElementById('id_location');
    const hint = document.getElementById('coords-hint');
    const startLat = parseFloat(latInput.value) || 28.6692;
    const startLng = parseFloat(lngInput.value) || 77.4538;

    const pickerMap = L.map('picker-map').setView([startLat, startLng], 14);
    L.tileLayer(STREET_TILE, { attribution: 'Tiles &copy; Esri' }).addTo(pickerMap);

    let marker = null;
    const reverseGeocode = (lat, lng) => {
      fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`)
        .then((r) => r.json())
        .then((data) => {
          if (data && data.display_name && locInput) {
            locInput.value = data.display_name.split(',').slice(0, 3).join(',');
          }
        })
        .catch(() => {});
    };

    const setPin = (lat, lng, autoFill = true) => {
      latInput.value = lat.toFixed(6);
      lngInput.value = lng.toFixed(6);
      hint.textContent = `Pinned coordinates: ${lat.toFixed(5)}, ${lng.toFixed(5)}`;
      if (marker) marker.setLatLng([lat, lng]);
      else marker = L.marker([lat, lng]).addTo(pickerMap);
      if (autoFill) reverseGeocode(lat, lng);
    };

    if (latInput.value && lngInput.value) setPin(startLat, startLng, false);
    pickerMap.on('click', (e) => setPin(e.latlng.lat, e.latlng.lng, true));

    const gpsBtn = document.getElementById('gps-btn');
    if (gpsBtn && navigator.geolocation) {
      gpsBtn.addEventListener('click', () => {
        gpsBtn.textContent = 'Locating...';
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            const { latitude, longitude } = pos.coords;
            pickerMap.setView([latitude, longitude], 16);
            setPin(latitude, longitude, true);
            gpsBtn.textContent = '✓ GPS Pinned';
          },
          () => { gpsBtn.textContent = 'GPS Unavailable'; }
        );
      });
    }
  }

  const titleInput = document.querySelector('[data-dup-check]');
  const voiceBtn = document.getElementById('voice-btn');
  if (voiceBtn && titleInput && ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SpeechRec();
    rec.lang = 'en-IN';
    voiceBtn.addEventListener('click', () => {
      voiceBtn.textContent = '🔴 Listening...';
      rec.start();
    });
    rec.onresult = (e) => {
      titleInput.value = e.results[0][0].transcript;
      titleInput.dispatchEvent(new Event('input'));
      voiceBtn.textContent = '🎙️ Voice Dictate';
    };
    rec.onerror = () => { voiceBtn.textContent = '🎙️ Voice Dictate'; };
  }

  const dupBox = document.getElementById('duplicate-alert');
  const triageBanner = document.getElementById('smart-triage-banner');
  const catSelect = document.getElementById('id_category');

  if (titleInput) {
    let timer;
    titleInput.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const q = titleInput.value.trim();
        if (q.length < 4) {
          if (dupBox) dupBox.style.display = 'none';
          if (triageBanner) triageBanner.style.display = 'none';
          return;
        }
        if (dupBox) {
          fetch(`${titleInput.dataset.dupCheck}?q=${encodeURIComponent(q)}`)
            .then((r) => r.json())
            .then((data) => {
              if (!data.matches.length) { dupBox.style.display = 'none'; return; }
              const links = data.matches.map((m) => `<a href="${m.url}">#${m.id} ${m.title}</a> (${m.upvotes} upvotes)`).join(' · ');
              dupBox.innerHTML = `<strong>Similar open issue already reported:</strong> ${links} — consider upvoting it instead.`;
              dupBox.style.display = 'block';
            });
        }
        if (triageBanner && titleInput.dataset.classifyUrl) {
          fetch(`${titleInput.dataset.classifyUrl}?text=${encodeURIComponent(q)}`)
            .then((r) => r.json())
            .then((data) => {
              if (!data.matched) { triageBanner.style.display = 'none'; return; }
              if (catSelect && !catSelect.value) catSelect.value = data.category_id;
              triageBanner.innerHTML = `<strong>AI Smart Auto-Triage:</strong> Matched <em>${data.category_name}</em> → Routing to <strong>${data.department}</strong> (Target SLA: ${data.sla_hours}h).`;
              triageBanner.style.display = 'block';
            });
        }
      }, 300);
    });
  }

  // 4. Detail Page Mini-Map & AJAX Upvote Button
  const miniMapEl = document.getElementById('detail-mini-map');
  if (miniMapEl && window.L) {
    const lat = parseFloat(miniMapEl.dataset.lat);
    const lng = parseFloat(miniMapEl.dataset.lng);
    const m = L.map('detail-mini-map').setView([lat, lng], 15);
    L.tileLayer(STREET_TILE).addTo(m);
    L.marker([lat, lng]).addTo(m);
  }

  const upvoteBtn = document.getElementById('upvote-btn');
  if (upvoteBtn) {
    upvoteBtn.addEventListener('click', () => {
      fetch(upvoteBtn.dataset.url, {
        method: 'POST',
        headers: { 'X-CSRFToken': upvoteBtn.dataset.csrf }
      })
        .then((r) => r.json())
        .then((data) => {
          document.getElementById('upvote-count').textContent = data.count;
          document.getElementById('upvote-label').textContent = data.upvoted ? 'Upvoted' : "I'm affected";
          upvoteBtn.classList.toggle('btn--ghost', !data.upvoted);
        });
    });
  }

  // 5. Kanban Drag-and-Drop Board
  const kanbanGrid = document.querySelector('.kanban-grid');
  if (kanbanGrid) {
    let draggedCard = null;
    kanbanGrid.querySelectorAll('.kanban-card').forEach((card) => {
      card.addEventListener('dragstart', () => { draggedCard = card; });
    });
    kanbanGrid.querySelectorAll('.kanban-col').forEach((col) => {
      col.addEventListener('dragover', (e) => e.preventDefault());
      col.addEventListener('drop', (e) => {
        e.preventDefault();
        if (!draggedCard) return;
        col.appendChild(draggedCard);
        fetch(draggedCard.dataset.moveUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': kanbanGrid.dataset.csrf
          },
          body: JSON.stringify({ status: col.dataset.status })
        });
      });
    });
  }

  // 6. Department Dashboard Chart.js Analytics
  const chartsGrid = document.querySelector('[data-stats-url]');
  if (chartsGrid && window.Chart) {
    fetch(chartsGrid.dataset.statsUrl)
      .then((r) => r.json())
      .then((data) => {
        new Chart(document.getElementById('trendChart'), {
          type: 'line',
          data: {
            labels: data.labels,
            datasets: [
              { label: 'Reported', data: data.reported, borderColor: '#d97706', tension: 0.3 },
              { label: 'Resolved', data: data.resolved, borderColor: '#16a34a', tension: 0.3 }
            ]
          },
          options: { responsive: true, plugins: { legend: { position: 'bottom' } } }
        });
      });
  }
});
"""
}

for filepath, content in V8_FILES.items():
    p = Path(filepath)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")

print("Successfully upgraded CivicPulse to v8 Sovereign Smart-City AI & Digital Twin Suite!")