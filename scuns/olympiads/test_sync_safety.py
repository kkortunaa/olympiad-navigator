"""Regression checks for unexpected disappearance of a published calendar."""
from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .models import Olympiad, OlympiadEvent, OlympiadProfile
from .services.sync import sync_catalog


class EmptyScheduleSafetyTests(TestCase):
    def setUp(self):
        self.olympiad = Olympiad.objects.create(
            season='2026/2027', catalog_number=1, name='Тестовая олимпиада',
            catalog_url='https://rsr-olymp.ru/', official_url='https://organizer.example/')
        self.math = OlympiadProfile.objects.create(
            olympiad=self.olympiad, name='математика', subjects='математика', level=1)
        self.code = OlympiadProfile.objects.create(
            olympiad=self.olympiad, name='информатика', subjects='информатика', level=1)
        self.entry = {
            'number': 1, 'name': self.olympiad.name,
            'official_url': 'https://organizer.example/',
            'profiles': [
                {'name': 'математика', 'subjects': 'математика', 'level': 1,
                 'official_url': 'https://organizer.example/'},
                {'name': 'информатика', 'subjects': 'информатика', 'level': 1,
                 'official_url': 'https://organizer.example/'},
            ],
        }

    def seed_event(self, profile_name, number=1):
        profile = {'математика': self.math, 'информатика': self.code}.get(profile_name)
        return OlympiadEvent.objects.create(
            olympiad=self.olympiad, profile=profile, profile_name=profile_name,
            name='Регистрация', kind='registration',
            starts_on=date(2026, 10, 1), ends_on=date(2026, 11, 1),
            dates_raw='1 октября — 1 ноября 2026',
            source_url='https://olimpiada.ru/activity/1/events/{}'.format(number),
            last_checked_at=timezone.now())

    def refresh(self, new_profiles=(), filtered=False):
        class Source:
            def get(self, *args, **kwargs):
                return '<html><body></body></html>'

        events = [{'url': 'https://olimpiada.ru/activity/1/events/{}'.format(index + 100),
                   'profile_name': name} for index, name in enumerate(new_profiles)]
        # Both subjects were read successfully, even when either timetable is empty.
        activities = [{'url': 'https://olimpiada.ru/activity/{}'.format(index + 1),
                       'profile_name': profile['name'], 'title': profile['name']}
                      for index, profile in enumerate(self.entry['profiles'])]
        activity = {'events': events, 'activities': activities, 'registration_url': ''}

        def read_event(html, url, profile_name, season):
            if filtered:
                return None
            return {'name': 'Отборочный этап', 'kind': 'stage',
                    'profile_name': profile_name,
                    'starts_on': date(2026, 11, 8), 'ends_on': date(2026, 11, 8),
                    'dates_raw': '8 ноября 2026', 'source_url': url,
                    'proof_url': '', 'registration_url': ''}

        with patch('olympiads.services.sync.parse_catalog', return_value=[self.entry]), \
                patch('olympiads.services.sync.source_index', return_value={}), \
                patch('olympiads.services.sync.source_urls', return_value=['https://olimpiada.ru/activity/1']), \
                patch('olympiads.services.sync.activity_data', return_value=activity), \
                patch('olympiads.services.sync.event_data', side_effect=read_event):
            return sync_catalog(Source(), '2026/2027', log=lambda message: None)

    def test_disappeared_profile_schedule_preserves_previous_dates(self):
        event = self.seed_event('информатика')
        run = self.refresh(new_profiles=('математика',))
        event.refresh_from_db()
        self.olympiad.refresh_from_db()
        self.assertEqual(run.status, 'partial')
        self.assertTrue(event.is_active)
        self.assertEqual(event.ends_on, date(2026, 11, 1))
        self.assertIn('информатика', self.olympiad.sync_error)

    def test_disappeared_common_schedule_preserves_previous_dates(self):
        event = self.seed_event('')
        run = self.refresh()
        event.refresh_from_db()
        self.olympiad.refresh_from_db()
        self.assertEqual(run.status, 'partial')
        self.assertTrue(event.is_active)
        self.assertIn('общее расписание', self.olympiad.sync_error)

    def test_filtered_events_do_not_erase_previous_profile_schedule(self):
        event = self.seed_event('информатика')
        run = self.refresh(new_profiles=('информатика',), filtered=True)
        event.refresh_from_db()
        self.assertEqual(run.status, 'partial')
        self.assertTrue(event.is_active)

    def test_removed_official_profile_does_not_prevent_reconciliation(self):
        event = self.seed_event('информатика')
        self.entry['profiles'] = self.entry['profiles'][:1]
        run = self.refresh()
        event.refresh_from_db()
        self.code.refresh_from_db()
        self.assertEqual(run.status, 'success')
        self.assertFalse(self.code.is_active)
        self.assertFalse(event.is_active)

    def test_initial_empty_schedule_remains_successful(self):
        run = self.refresh()
        self.olympiad.refresh_from_db()
        self.assertEqual(run.status, 'success')
        self.assertEqual(self.olympiad.sync_error, '')
        self.assertFalse(self.olympiad.events.exists())
