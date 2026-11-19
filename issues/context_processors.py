from django.core.cache import cache


def nav_badges(request):
    broadcast_msg = cache.get('civicpulse_emergency_broadcast', '')
    if not request.user.is_authenticated:
        return {
            'is_official': False,
            'unread_notifications': [],
            'unread_count': 0,
            'emergency_broadcast': broadcast_msg,
        }
    is_official = request.user.is_staff or request.user.departments.exists()
    unread_qs = request.user.notifications.filter(is_read=False).select_related('issue')
    return {
        'is_official': is_official,
        'unread_notifications': unread_qs[:5],
        'unread_count': unread_qs.count(),
        'emergency_broadcast': broadcast_msg,
    }


role_context = nav_badges
