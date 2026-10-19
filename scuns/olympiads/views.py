import re
from datetime import date

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from .models import Olympiad, ScrapeRun
from .registration import registration_periods, registration_estimates
from .link_display import prepare_catalog_links


def filter_metadata(olympiads):
    metadata, subjects, profiles = {}, set(), set()
    for olympiad in olympiads:
        items = []
        for profile in olympiad.profiles.all():
            if not profile.is_active:
                continue
            names = [value.strip() for value in re.split(r',(?!\s*лесное и рыбное хозяйство\b)\s*', profile.subjects) if value.strip()]
            subjects.update(names)
            profiles.add(profile.name)
            items.append({'name': profile.name, 'subjects': names})
        metadata[olympiad.plan_key] = {
            'number': olympiad.catalog_number, 'name': olympiad.name, 'profiles': items,
            'registrations': registration_periods(olympiad),
        }
    return {'catalog_metadata': metadata, 'catalog_subjects': sorted(subjects),
            'catalog_profiles': sorted(profiles)}


def catalog_context():
    today = timezone.localdate()
    start = today.year if today.month >= 8 else today.year - 1
    season = '{}/{}'.format(start, start + 1)
    olympiads = list(Olympiad.objects.filter(season=season, is_active=True).prefetch_related('events', 'profiles'))
    prepare_catalog_links(olympiads)
    run = ScrapeRun.objects.filter(season=season, finished_at__isnull=False).first()
    filters = filter_metadata(olympiads)
    return {'catalog': olympiads, 'catalog_season': season, 'catalog_run': run,
            'catalog_today': today.isoformat(),
            'subject_choices': [{'value': value, 'label': value[:1].upper() + value[1:]} for value in filters['catalog_subjects']],
            'profile_choices': [{'value': value, 'label': value[:1].upper() + value[1:]} for value in filters['catalog_profiles']],
            'sort_choices': [{'value': key, 'label': label} for key, label in [
                ('registration-asc', 'Ближайшее окончание регистрации'), ('registration-start-asc', 'Ближайшее открытие регистрации'),
                ('registration-desc', 'Позднее окончание регистрации'), ('registration-start-desc', 'Позднее открытие регистрации'),
                ('name', 'По названию'), ('catalog', 'По номеру в перечне')]],
            **filters}


def detail(request, pk):
    olympiad = get_object_or_404(Olympiad.objects.prefetch_related('profiles', 'events'), pk=pk)
    prepare_catalog_links([olympiad])
    return render(request, 'olympiads/detail.html', {'olympiad': olympiad,
        'active_page': 'olympiads', 'page_title': olympiad.name,
        'schedule': sorted([event for event in olympiad.events.all() if event.is_active],
                           key=lambda event: ({'registration': 0, 'stage': 1}.get(event.kind, 2), event.starts_on or event.ends_on or date.max, event.profile_name, event.name)),
        'profiles': [profile for profile in olympiad.profiles.all() if profile.is_active],
        'registration_estimates': registration_estimates(olympiad)})


def catalog_api(request):
    data = catalog_context()
    rows = []
    for item in data['catalog']:
        rows.append({'id': item.pk, 'key': item.plan_key, 'name': item.name, 'season': item.season,
            'catalog_number': item.catalog_number, 'official_url': item.official_url,
            'registration_url': item.registration_url or None, 'source_url': item.source_url,
            'registration_action': item.registration_action,
            'last_success_at': item.last_success_at,
            'registration_estimates': registration_estimates(item),
            'profiles': [{'id': profile.pk, 'name': profile.name, 'level': profile.level, 'subjects': profile.subjects,
                'tasks_url': profile.tasks_url or None, 'tasks_checked_at': profile.tasks_checked_at,
                'registration_url': profile.registration_url or None,
                'registration_action': profile.registration_action} for profile in item.profiles.all() if profile.is_active],
            'events': [{'name': event.name, 'kind': event.kind, 'profile': event.profile_name,
                'starts_on': event.starts_on, 'ends_on': event.ends_on, 'dates_raw': event.dates_raw,
                'registration_url': event.registration_url or None, 'source_url': event.source_url,
                'proof_url': event.proof_url, 'participation_format': event.participation_format or None,
                'venue': event.venue or None, 'venue_url': event.venue_url or None,
                'venue_source_url': event.venue_source_url or None, 'venue_note': event.venue_note or None,
                'venue_basis': event.venue_basis or None, 'venue_checked_at': event.venue_checked_at} for event in item.events.all() if event.is_active]})
    return JsonResponse({'season': data['catalog_season'], 'count': len(rows), 'olympiads': rows}, json_dumps_params={'ensure_ascii': False})
