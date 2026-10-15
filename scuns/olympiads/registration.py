"""Registration presentation: published dates and explicitly labelled estimates."""
import re
from django.utils import timezone

QUALIFYING = re.compile(r'отбор|перв(?:ый|ого|ом)\s+(?:тур|этап)|^I\s+(?:тур|этап)', re.I)


def registration_estimates(olympiad):
    """Never write inferred registration dates to published event records."""
    events = [event for event in olympiad.events.all() if event.is_active]
    registrations = [event for event in events if event.kind == 'registration']
    stages = [event for event in events if event.kind == 'stage'
              and QUALIFYING.search(event.name) and event.starts_on]
    today = timezone.localdate()
    result = []
    for profile in olympiad.profiles.all():
        if not profile.is_active:
            continue
        applicable = [event for event in registrations if event.profile_name in ('', profile.name)]
        if any(event.ends_on for event in applicable):
            continue
        candidates = [event for event in stages if event.profile_name in ('', profile.name)]
        published_starts = [event.starts_on for event in applicable if event.starts_on]
        if published_starts:
            candidates = [event for event in candidates if event.starts_on >= max(published_starts)]
        if not candidates:
            continue
        upcoming = [event for event in candidates if (event.ends_on or event.starts_on) >= today]
        stage = min(upcoming, key=lambda event: event.starts_on) if upcoming else max(candidates, key=lambda event: event.starts_on)
        result.append({'profile': profile.name, 'deadline': stage.starts_on,
                       'stage': stage.name, 'stage_start': stage.starts_on, 'stage_end': stage.ends_on,
                       'source_url': stage.source_url, 'estimated': True,
                       'explanation': 'Подтверждённый срок регистрации не найден. Ориентир — зарегистрироваться до начала отборочного тура; уточни условия у организатора.'})
    return result


def registration_periods(olympiad):
    periods = [{'profile': event.profile_name, 'name': event.name,
                'starts_on': event.starts_on.isoformat() if event.starts_on else None,
                'ends_on': event.ends_on.isoformat() if event.ends_on else None,
                'deadline': event.ends_on.isoformat() if event.ends_on else None,
                'source_url': event.source_url, 'checked_at': event.last_checked_at.isoformat(),
                'estimated': False}
               for event in olympiad.events.all() if event.is_active and event.kind == 'registration']
    for estimate in registration_estimates(olympiad):
        # A start-only registration remains visible, with its published opening date.
        partial = [item for item in periods if item['profile'] == estimate['profile'] and not item['ends_on']]
        target = min(partial, key=lambda item: item['starts_on'] or '') if partial else None
        if target:
            target.update({'ends_on': estimate['deadline'].isoformat(), 'deadline': estimate['deadline'].isoformat(),
                           'estimated': True, 'estimate_source_url': estimate['source_url'],
                           'estimate_explanation': estimate['explanation']})
        else:
            periods.append({'profile': estimate['profile'], 'name': 'Ориентир до отборочного тура',
                            'starts_on': None, 'ends_on': estimate['deadline'].isoformat(),
                            'deadline': estimate['deadline'].isoformat(), 'source_url': estimate['source_url'],
                            'estimated': True, 'estimate_source_url': estimate['source_url'],
                            'estimate_explanation': estimate['explanation'], 'checked_at': None})
    return periods
