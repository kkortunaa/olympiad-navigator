from .models import AssignmentReceipt
from .views import notice_queryset
from practice.models import Recipient


def school_context(request):
    authenticated = request.user.is_authenticated
    unread = notice_queryset(request.user).filter(read_at__isnull=True).count() if authenticated else 0
    pending = []
    pending_variants = []
    if authenticated and not request.user.is_teacher and request.path == '/':
        pending = AssignmentReceipt.objects.filter(membership__student=request.user, membership__is_active=True,
            completed_at__isnull=True).select_related('assignment__classroom').order_by('assignment__due_on', 'pk')[:4]
        pending_variants = Recipient.objects.filter(membership__student=request.user, membership__is_active=True).exclude(
            attempts__status='submitted').select_related('assignment__classroom').order_by('-assignment__created_at')[:4]
    return {'school_bootstrap': {'authenticated': authenticated, 'unread': unread,
                                'user': request.user.pk if authenticated else None, 'teacher': authenticated and request.user.is_teacher},
            'school_unread': unread, 'school_pending_assignments': pending, 'school_pending_variants': pending_variants}
