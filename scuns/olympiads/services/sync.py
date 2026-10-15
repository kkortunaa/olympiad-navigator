from bs4 import BeautifulSoup
from django.db import transaction
from django.utils import timezone

from olympiads.models import Olympiad, OlympiadProfile, OlympiadEvent, ScrapeRun
from .venues import activity_venue_data, merge_venue_data
from .parsing import (OFFICIAL_CATALOG, INDEX_URL, parse_catalog, source_index, source_urls,
                      activity_data, event_data, registration_link, profile_registration_links, task_archive_link)


def sync_catalog(source, season, index_url=INDEX_URL, limit=None, log=print):
    run = ScrapeRun.objects.create(season=season)
    errors = []
    successful = 0
    try:
        catalog = parse_catalog(source.get(OFFICIAL_CATALOG, '.mainTableInfo tbody'), season)
        index = source_index(source.get(index_url, 'ol a[href*="/activity/"]'))
        # Commit the complete approved catalog first, even if a schedule page is unavailable.
        with transaction.atomic():
            for item in catalog:
                urls = source_urls(item['name'], index)
                olympiad, _ = Olympiad.objects.update_or_create(season=season, catalog_number=item['number'], defaults={
                    'name': item['name'], 'official_url': item['official_url'], 'catalog_url': OFFICIAL_CATALOG,
                    'subjects': [profile['name'] for profile in item['profiles']], 'is_active': True,
                    **({'source_url': urls[0]} if urls else {}),
                })
                for profile in item['profiles']:
                    OlympiadProfile.objects.update_or_create(olympiad=olympiad, name=profile['name'], defaults={
                        'subjects': profile['subjects'], 'level': profile['level'],
                        'official_url': profile['official_url'], 'is_active': True,
                    })
                olympiad.profiles.exclude(name__in=[p['name'] for p in item['profiles']]).update(is_active=False)
            Olympiad.objects.filter(season=season).exclude(catalog_number__in=[o['number'] for o in catalog]).update(is_active=False)
        log('Перечень: {} олимпиад, {} профилей.'.format(len(catalog), sum(len(o['profiles']) for o in catalog)))
        for item in catalog[:limit] if limit else catalog:
            olympiad = Olympiad.objects.get(season=season, catalog_number=item['number'])
            olympiad.last_checked_at = timezone.now()
            issue = []
            events = {}
            activities = {}
            general_link = ''
            organizer_links = {}
            organizer_profile_links = {}
            event_registration = {}
            urls = source_urls(item['name'], index)
            log('[{}/{}] {}'.format(item['number'], len(catalog), item['name']))
            for url in urls:
                try:
                    data = activity_data(source.get(url, '.top_container'), url, item['profiles'])
                    events.update({(entry['url'], entry['profile_name']): entry for entry in data['events']})
                    activities.update({entry['url']: entry for entry in data['activities']})
                    if data['registration_url']:
                        general_link = data['registration_url']
                except Exception as exc:
                    issue.append(str(exc))
            if not urls:
                issue.append('Нет точного соответствия карточке Олимпиада.ру.')
            if not activities and urls and not issue:
                issue.append('Не удалось сопоставить предметные карточки утвержденным профилям.')
            elif activities and all(activity['profile_name'] for activity in activities.values()):
                # A shared activity (empty profile_name) legitimately applies to every
                # approved profile. A partially matched multi-subject page does not:
                # treating it as complete would erase earlier dates for missing subjects.
                matched = {activity['profile_name'] for activity in activities.values()}
                missing = sorted({profile['name'] for profile in item['profiles']} - matched)
                if missing:
                    issue.append('Не сопоставлены предметные карточки: ' + ', '.join(missing) + '.')
            # Fetch full events: timeline dates can be clipped to fit the academic year.
            event_ids = []
            profile_map = {profile.name: profile for profile in olympiad.profiles.filter(is_active=True)}
            previous_profiles = set(olympiad.events.filter(is_active=True).values_list('profile_name', flat=True))
            required_profiles = previous_profiles & set(profile_map)
            if '' in previous_profiles:
                # A common calendar supplied dates for every approved profile.
                required_profiles.update(profile_map)
            received_profiles = set()
            for number, entry in enumerate(events.values(), 1):
                try:
                    data = event_data(source.get(entry['url'], '.time_classes_line_for_event'), entry['url'], entry['profile_name'], season)
                    if data is None:
                        continue
                    profile = profile_map.get(entry['profile_name'])
                    if data['kind'] == 'stage':
                        if not (data.get('venue') or data.get('venue_url')):
                            activity_url = entry['url'].split('/events/', 1)[0]
                            try:
                                venue = activity_venue_data(source.get(activity_url, '.top_container'), data['name'], activity_url, season)
                                keys=('participation_format','venue','venue_url','venue_source_url','venue_note','venue_basis')
                                direct={key:data[key] for key in keys if key in data}
                                data.update(merge_venue_data(direct,venue))
                            except Exception as exc:
                                errors.append({'number': item['number'], 'type': 'venue', 'message': str(exc)})
                                # Keep the previous venue if the supplementary venue source is unavailable.
                                for key in ('participation_format','venue','venue_url','venue_source_url','venue_note','venue_basis'):
                                    data.pop(key, None)
                        if data.get('venue_source_url'):
                            data['venue_checked_at'] = timezone.now()
                    event, _ = OlympiadEvent.objects.update_or_create(olympiad=olympiad, source_url=entry['url'], profile_name=entry['profile_name'], defaults={
                        **data, 'profile': profile, 'last_checked_at': timezone.now(), 'is_active': True,
                    })
                    event_ids.append(event.pk)
                    received_profiles.add(event.profile_name)
                    if data['kind'] == 'registration' and data['registration_url']:
                        if profile:
                            event_registration[profile.name] = data['registration_url']
                        if (not profile or len(item['profiles']) == 1) and not general_link:
                            general_link = data['registration_url']
                except Exception as exc:
                    issue.append(str(exc))
                if number % 15 == 0:
                    log('  События: {}/{}'.format(number, len(events)))
            if not issue:
                # Recognising a subject heading does not prove that its empty
                # calendar is intentional. A markup change or a seasonal filter
                # can otherwise silently deactivate every previously known date.
                # Profiles removed from the approved catalog are not protected.
                confirmed_profiles = set(profile_map) if '' in received_profiles else received_profiles
                missing = sorted(required_profiles - confirmed_profiles)
                if missing or ('' in previous_profiles and not event_ids):
                    description = 'общее расписание' if '' in previous_profiles and not event_ids else 'профили: ' + ', '.join(missing)
                    issue.append('Источник не подтвердил ранее опубликованные даты ({}); сохранены предыдущие данные.'.format(description))
            for activity in activities.values():
                profile = profile_map.get(activity['profile_name'])
                if profile:
                    profile.source_url = activity['url']
                    profile.save(update_fields=['source_url'])
                # Archive discovery is independent of schedule completeness.
                # Failed reads retain an already known archive link.
                try:
                    archive = task_archive_link(source.get(activity['url'], '.top_container'), activity['url'])
                    if archive:
                        targets = [profile] if profile else list(profile_map.values())
                        for target in targets:
                            target.tasks_url = archive
                            target.tasks_checked_at = timezone.now()
                            target.save(update_fields=['tasks_url', 'tasks_checked_at'])
                except Exception as exc:
                    errors.append({'number': item['number'], 'type': 'task_link', 'message': str(exc)})
            # Discover registration links on official organiser pages (one read per URL).
            official_urls = {profile['official_url'] for profile in item['profiles'] if profile['official_url']}
            for official in sorted(official_urls):
                try:
                    # Official pages can be unavailable while timetable data remains valid.
                    soup = BeautifulSoup(source.get(official, timeout=10, retries=1), 'html.parser')
                    registration = registration_link(soup, official, generic=True)
                    organizer_profile_links.update({(official, name): link for name, link
                        in profile_registration_links(soup, official, item['profiles']).items()})
                    organizer_links[official] = registration
                    if official == item['official_url']:
                        general_link = registration or general_link
                except Exception as exc:
                    errors.append({'number': item['number'], 'type': 'registration_link', 'message': str(exc)})
            if item['official_url'] in organizer_links or general_link:
                olympiad.registration_url = general_link
            for profile in profile_map.values():
                if profile.name in event_registration:
                    profile.registration_url = event_registration[profile.name]
                elif (profile.official_url, profile.name) in organizer_profile_links:
                    profile.registration_url = organizer_profile_links[(profile.official_url, profile.name)]
                elif profile.official_url in organizer_links:
                    profile.registration_url = organizer_links[profile.official_url] or general_link
                else:
                    continue
                profile.save(update_fields=['registration_url'])
            if not issue:
                # Failed/partial reads retain previous schedules; successful reads reconcile them.
                olympiad.events.exclude(pk__in=event_ids).update(is_active=False)
                olympiad.last_success_at = timezone.now()
                successful += 1
            olympiad.sync_error = '\n'.join(issue)
            olympiad.save()
            errors.extend({'number': item['number'], 'type': 'schedule', 'message': message} for message in issue)
            log('  Дат: {}. {}'.format(len(event_ids), 'Сохранено.' if not issue else 'Ошибок: {} (прежние данные сохранены).'.format(len(issue))))
        run.status = 'partial' if errors or (limit and limit < len(catalog)) else 'success'
    except KeyboardInterrupt:
        run.status = 'interrupted'
        errors.append({'type': 'interrupted', 'message': 'Сбор остановлен пользователем.'})
        raise
    except Exception as exc:
        run.status = 'failed'
        errors.append({'type': 'catalog', 'message': str(exc)})
        raise
    finally:
        run.finished_at = timezone.now()
        run.errors = errors
        run.olympiad_count = Olympiad.objects.filter(season=season, is_active=True).count()
        run.profile_count = OlympiadProfile.objects.filter(olympiad__season=season, is_active=True).count()
        run.event_count = OlympiadEvent.objects.filter(olympiad__season=season, is_active=True).count()
        run.save()
    log('Результат: {}. Олимпиад: {}, профилей: {}, событий: {}, замечаний: {}.'.format(
        run.status, run.olympiad_count, run.profile_count, run.event_count, len(errors)))
    return run
