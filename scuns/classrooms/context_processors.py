from .models import AssignmentReceipt
from .views import notice_queryset


def school_context(request):
    authenticated = request.user.is_authenticated
    unread = notice_queryset(request.user).filter(read_at__isnull=True).count() if authenticated else 0
    pending = []
    if authenticated and not request.user.is_teacher and request.path == '/':
        pending = AssignmentReceipt.objects.filter(membership__student=request.user, membership__is_active=True,
            completed_at__isnull=True).select_related('assignment__classroom').order_by('assignment__due_on', 'pk')[:4]
    return {'school_bootstrap': {'authenticated': authenticated, 'unread': unread,
                                'user': request.user.pk if authenticated else None, 'teacher': authenticated and request.user.is_teacher},
            'school_unread': unread, 'school_pending_assignments': pending}
