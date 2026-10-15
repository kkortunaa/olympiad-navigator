from olympiads.models import Olympiad
from django.utils import timezone
from .models import Workspace
from .state import STATUSES


def personal_planner(request):
    bootstrap = {'authenticated': request.user.is_authenticated, 'today': timezone.localdate().isoformat(), 'statuses': STATUSES}
    if request.user.is_authenticated:
        workspace, _ = Workspace.objects.get_or_create(user=request.user)
        bootstrap.update({'user': request.user.pk, 'state': workspace.state, 'revision': workspace.revision})
    if request.user.is_authenticated and not request.user.is_teacher:
        bootstrap['registered_profiles'] = [{'id': str(item.profile_id), 'key': item.profile.olympiad.plan_key}
            for item in request.user.olympiad_registrations.filter(profile__is_active=True, profile__olympiad__is_active=True).select_related('profile__olympiad')]
    rows = []
    for item in Olympiad.objects.filter(is_active=True).prefetch_related('profiles', 'events'):
        rows.append({'key': item.plan_key, 'name': item.name, 'url': '/olympiads/{}/'.format(item.pk),
                     'season': item.season,
                     'profiles': [{'id': str(profile.pk), 'name': profile.name, 'subjects': profile.subjects,
                                   'tasks_url': profile.tasks_url} for profile in item.profiles.all() if profile.is_active],
                     'events': [{'id': event.pk, 'name': event.name, 'kind': event.kind, 'profile': event.profile_name,
                                 'start': event.starts_on.isoformat() if event.starts_on else None,
                                 'end': event.ends_on.isoformat() if event.ends_on else None,
                                 'url': event.source_url} for event in item.events.all() if event.is_active]})
    return {'personal_bootstrap': bootstrap, 'planner_catalog': rows, 'participation_statuses': STATUSES}
