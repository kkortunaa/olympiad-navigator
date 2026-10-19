from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from django.apps import apps
from django.db import connection
from django.test import SimpleTestCase, TestCase

from .management.commands.audit_catalog_links import check_link
from .services.parsing import safe_url


class CatalogLinkTests(SimpleTestCase):
    def test_old_yumsh_hosts_are_corrected_on_import(self):
        for scheme in ('http', 'https'):
            for host in ('yumsh.spbu.ru', 'www.yumsh.spbu.ru'):
                for ending in ('', '/'):
                    self.assertEqual(safe_url(f'{scheme}://{host}{ending}'),
                                     'https://yumsh.ru/cms/yumsh-olymp')

    def test_other_paths_and_registration_forms_are_preserved(self):
        for url in ('https://yumsh.ru/cms/yumsh-olymp/2026-27',
                    'https://yumsh.spbu.ru/archive/2020',
                    'https://forms.example/current-registration/'):
            self.assertEqual(safe_url(url), url)
        self.assertEqual(safe_url('javascript:alert(1)'), '')

    def test_obsolete_registration_is_not_reimported(self):
        self.assertEqual(safe_url('https://form.centraluniversity.ru/youth_math_olympiad/'), '')

    def test_verified_moved_organizers_are_corrected(self):
        self.assertEqual(safe_url('http://abiturient.tsu.ru/ru/content/ormo/'),
                         'https://info.abiturient.tsu.ru/ru/content/ormo')
        self.assertEqual(safe_url('http://ntcontest.ru'), 'https://ntcontest.ru/')
        self.assertEqual(safe_url('http://www.olympiads.ru/zaoch/'), 'https://inf-open.ru/')

    @patch('olympiads.management.commands.audit_catalog_links.urlopen')
    def test_audit_handles_cyrillic_domains_and_paths(self, urlopen):
        response = MagicMock(status=200)
        response.read.return_value = b'<title>Olympiad</title>'
        response.geturl.return_value = 'https://example.com/'
        urlopen.return_value.__enter__.return_value = response
        result = check_link('https://турлом.цпм.рф/как-участвовать/#instr', 10)
        self.assertEqual(result['outcome'], 'reachable')
        wire_url = urlopen.call_args.args[0].full_url
        self.assertTrue(wire_url.isascii())
        self.assertIn('xn--', wire_url)
        self.assertIn('%D0', wire_url)

    @patch('olympiads.management.commands.audit_catalog_links.urlopen')
    def test_forbidden_pages_are_not_reported_as_removed(self, urlopen):
        for status, expected in ((403, 'access_or_server_error'), (404, 'not_found')):
            urlopen.side_effect = HTTPError('https://example.com/', status, '', {}, None)
            self.assertEqual(check_link('https://example.com/', 10)['outcome'], expected)

    @patch('olympiads.management.commands.audit_catalog_links.urlopen')
    def test_service_unavailable_page_with_http_200_is_not_a_working_form(self, urlopen):
        response = MagicMock(status=200)
        response.read.return_value = '<title>Сервисы временно недоступны</title>'.encode()
        response.geturl.return_value = 'https://my.ntcontest.ru/'
        urlopen.return_value.__enter__.return_value = response
        self.assertEqual(check_link('https://my.ntcontest.ru/', 10)['outcome'], 'temporarily_unavailable')

    def test_registration_discovery_rejects_admin_pages(self):
        from bs4 import BeautifulSoup
        from .services.parsing import registration_link
        soup = BeautifulSoup('<a href="https://example.com/admin/content/profiles">Регистрация</a>', 'html.parser')
        self.assertEqual(registration_link(soup, 'https://example.com/'), '')


class RegistrationFallbackTests(TestCase):
    def setUp(self):
        from .models import Olympiad, OlympiadProfile, CatalogLinkCheck, OlympiadEvent
        from django.utils import timezone
        self.olympiad = Olympiad.objects.create(season='2026/2027', catalog_number=1,
            name='Тестовая олимпиада', official_url='https://organizer.example/',
            source_url='https://olimpiada.ru/activity/1', catalog_url='https://rsr-olymp.ru/',
            registration_url='https://forms.example/')
        self.profile = OlympiadProfile.objects.create(olympiad=self.olympiad, name='математика',
            level=1, official_url=self.olympiad.official_url, registration_url=self.olympiad.registration_url)
        OlympiadEvent.objects.create(olympiad=self.olympiad, profile=self.profile, name='Регистрация',
            kind='registration', registration_url=self.olympiad.registration_url,
            source_url='https://olimpiada.ru/activity/1/events/1', last_checked_at=timezone.now())
        self.check = CatalogLinkCheck.objects.create(url=self.olympiad.registration_url,
                                                    outcome='connection_error')

    def test_failed_form_is_removed_from_card_detail_profiles_events_and_api(self):
        from datetime import date
        with patch('olympiads.views.timezone.localdate', return_value=date(2026, 10, 19)):
            for path in ('/olympiads/', f'/olympiads/{self.olympiad.pk}/'):
                response = self.client.get(path)
                self.assertNotContains(response, 'href="https://forms.example/"')
                self.assertContains(response, 'href="https://organizer.example/"')
                self.assertContains(response, 'Прямая форма')
            data = self.client.get('/api/olympiads/').json()['olympiads'][0]
        self.assertIsNone(data['registration_url'])
        self.assertIsNone(data['profiles'][0]['registration_url'])
        self.assertIsNone(data['events'][0]['registration_url'])
        self.olympiad.refresh_from_db()
        self.assertEqual(self.olympiad.registration_url, 'https://forms.example/')

    def test_failed_organizer_uses_source_without_labelling_it_as_direct_registration(self):
        from .models import CatalogLinkCheck
        CatalogLinkCheck.objects.create(url=self.olympiad.official_url, outcome='not_found')
        response = self.client.get(f'/olympiads/{self.olympiad.pk}/')
        self.assertContains(response, 'Условия участия и источники')
        self.assertNotContains(response, 'href="https://organizer.example/"')

    def test_successful_recheck_restores_original_form(self):
        self.check.outcome = 'reachable'
        self.check.save()
        response = self.client.get(f'/olympiads/{self.olympiad.pk}/')
        self.assertContains(response, 'href="https://forms.example/"')

    def test_bot_restriction_does_not_hide_a_valid_form(self):
        self.check.outcome = 'restricted'
        self.check.save()
        response = self.client.get(f'/olympiads/{self.olympiad.pk}/')
        self.assertContains(response, 'href="https://forms.example/"')

    @patch('olympiads.management.commands.audit_catalog_links.check_link')
    def test_audit_saves_recovery_without_changing_original_urls(self, check_link):
        from django.core.management import call_command
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from io import StringIO
        check_link.side_effect = lambda url, timeout: {
            'url': url, 'outcome': 'reachable', 'status': 200, 'final_url': url}
        with TemporaryDirectory() as folder:
            call_command('audit_catalog_links', report=str(Path(folder) / 'audit.json'),
                         save_checks=True, workers=1, stdout=StringIO())
        self.check.refresh_from_db()
        self.assertEqual(self.check.outcome, 'reachable')
        self.olympiad.refresh_from_db()
        self.assertEqual(self.olympiad.registration_url, 'https://forms.example/')


class YumshRegistrationMigrationTests(TestCase):
    def test_existing_records_and_rendered_button_use_organizer_fallback(self):
        from importlib import import_module
        from .models import Olympiad, OlympiadProfile, OlympiadEvent
        from django.utils import timezone

        stale = 'https://form.centraluniversity.ru/youth_math_olympiad/'
        official = 'https://yumsh.ru/cms/yumsh-olymp'
        olympiad = Olympiad.objects.create(season='2026/2027', catalog_number=45,
            name='Олимпиада Юношеской математической школы', official_url=official,
            registration_url=stale, catalog_url='https://rsr-olymp.ru/')
        profile = OlympiadProfile.objects.create(olympiad=olympiad,
            name='математика', level=3, official_url=official, registration_url=stale)
        event = OlympiadEvent.objects.create(olympiad=olympiad, profile=profile,
            name='Регистрация', kind='registration', registration_url=stale,
            source_url='https://olimpiada.ru/activity/1/events/1', last_checked_at=timezone.now())
        migration = import_module('olympiads.migrations.0007_remove_obsolete_yumsh_registration')
        migration.remove_obsolete_registration(apps, type('Editor', (), {'connection': connection})())
        for item in (olympiad, profile, event):
            item.refresh_from_db()
            self.assertEqual(item.registration_url, '')
        response = self.client.get(f'/olympiads/{olympiad.pk}/')
        self.assertContains(response, f'href="{official}"')
        self.assertContains(response, 'Регистрация на сайте организатора')
        self.assertNotContains(response, stale)
