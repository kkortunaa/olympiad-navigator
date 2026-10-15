"""Refresh published registration events without replacing tour calendars."""
import json
from django.core.management.base import BaseCommand
from django.utils import timezone
from olympiads.models import Olympiad, OlympiadEvent
from olympiads.services.browser import SeleniumSource
from olympiads.services.parsing import registration_references, event_data


class Command(BaseCommand):
    help = 'Повторно проверить сроки регистрации для профилей без подтверждённого дедлайна.'

    def add_arguments(self, parser):
        parser.add_argument('--season', help='Учебный год; по умолчанию текущий.')
        parser.add_argument('--driver-path')
        parser.add_argument('--timeout', type=int, default=12)
        parser.add_argument('--report', default='registration-refresh-report.json')

    def handle(self, *args, **options):
        today = timezone.localdate()
        year = today.year if today.month >= 8 else today.year - 1
        season = options['season'] or '{}/{}'.format(year, year+1)
        report = {'started_at': timezone.now().isoformat(), 'season': season,
                  'checked_pages': 0, 'saved_events': 0, 'new_events': 0, 'errors': [], 'olympiads': []}
        source = None
        try:
            source = SeleniumSource(driver_path=options['driver_path'], timeout=options['timeout'], delay=0.15)
            olympiads = Olympiad.objects.filter(is_active=True, season=season).prefetch_related('profiles', 'events')
            for olympiad in olympiads:
                profiles = [profile for profile in olympiad.profiles.all() if profile.is_active]
                registrations = [event for event in olympiad.events.all() if event.is_active and event.kind == 'registration' and event.ends_on]
                missing = [profile for profile in profiles if not any(event.profile_name in ('', profile.name) for event in registrations)]
                if not missing:
                    continue
                self.stdout.write('{}: {} — проверяем {} профилей'.format(olympiad.catalog_number, olympiad.name, len(missing)))
                self.stdout.flush()
                requests = [(olympiad.source_url, profiles)] if olympiad.source_url else []
                requests += [(profile.source_url, [profile]) for profile in missing if profile.source_url and profile.source_url != olympiad.source_url]
                references = {}
                for url, targets in requests:
                    try:
                        html = source.get(url, '.top_container', retries=1)
                        report['checked_pages'] += 1
                        entries = registration_references(html, url, [{'name': profile.name} for profile in targets])
                        references.update({(entry['url'], entry['profile_name']): entry for entry in entries})
                    except Exception as exc:
                        report['errors'].append({'number': olympiad.catalog_number, 'url': url, 'error': str(exc)})
                saved = 0
                profile_map = {profile.name: profile for profile in profiles}
                for entry in references.values():
                    try:
                        html = source.get(entry['url'], '.time_classes_line_for_event', retries=1)
                        data = event_data(html, entry['url'], entry['profile_name'], season)
                        if not data or data['kind'] != 'registration':
                            continue
                        _, created = OlympiadEvent.objects.update_or_create(
                            olympiad=olympiad, source_url=entry['url'], profile_name=entry['profile_name'],
                            defaults={**data, 'profile': profile_map.get(entry['profile_name']),
                                      'last_checked_at': timezone.now(), 'is_active': True})
                        saved += 1; report['saved_events'] += 1; report['new_events'] += int(created)
                    except Exception as exc:
                        report['errors'].append({'number': olympiad.catalog_number, 'url': entry['url'], 'error': str(exc)})
                report['olympiads'].append({'number': olympiad.catalog_number, 'profiles_without_deadline': len(missing), 'saved_events': saved})
                self.stdout.write('  Подтверждённых событий регистрации обновлено: {}.'.format(saved))
                self.stdout.flush()
        finally:
            if source:
                source.close()
            report['finished_at'] = timezone.now().isoformat()
            with open(options['report'], 'w', encoding='utf-8') as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
        self.stdout.write('Страниц: {}. Событий обновлено: {}. Новых: {}. Ошибок: {}.'.format(
            report['checked_pages'], report['saved_events'], report['new_events'], len(report['errors'])))
