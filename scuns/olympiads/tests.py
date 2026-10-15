from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup
from django.test import TestCase, SimpleTestCase

from .models import OlympiadEvent, Olympiad, OlympiadProfile, ScrapeRun
from .services.parsing import (parse_date_display, activity_data, registration_link,
                               profile_registration_links, event_data, parse_catalog,
                               profile_match, safe_url)
from .services.sync import sync_catalog
from .views import filter_metadata


class DateParsingTests(SimpleTestCase):
    def parse(self, html):
        return parse_date_display(BeautifulSoup(html, 'html.parser').select_one('.main_date'))

    def test_registration_deadline_uses_full_dates_not_cropped_timeline(self):
        starts, ends, _ = self.parse('<span class="main_date"><font>20...22</font><span class="month">августа</span><span class="month">сентября</span><span class="month">2026</span></span>')
        self.assertEqual(starts, date(2026, 8, 20))
        self.assertEqual(ends, date(2026, 9, 22))

    def test_cross_year_tour_range(self):
        starts, ends, _ = self.parse('<span class="main_date"><font>28...5</font><span class="month">декабря</span><span class="month">января</span><span class="month">2026...2027</span></span>')
        self.assertEqual(starts, date(2026, 12, 28))
        self.assertEqual(ends, date(2027, 1, 5))

    def test_missing_or_approximate_dates_are_not_invented(self):
        starts, ends, raw = self.parse('<span class="main_date"><span class="month">февраль 2027</span></span>')
        self.assertIsNone(starts)
        self.assertIsNone(ends)
        self.assertIn('2027', raw)

    def test_bad_date_is_not_silently_rolled_into_next_month(self):
        starts, ends, _ = self.parse('<span class="main_date"><font>31</font><span class="month">февраля</span><span class="month">2027</span></span>')
        self.assertIsNone(starts)
        self.assertIsNone(ends)

    def test_deadline_without_start_date(self):
        starts, ends, _ = self.parse('<span class="main_date"><font>До</font><font>21</font><span class="month">октября</span><span class="month">2026</span></span>')
        self.assertIsNone(starts)
        self.assertEqual(ends, date(2026, 10, 21))

    def test_start_without_deadline(self):
        starts, ends, _ = self.parse('<span class="main_date"><font>С</font><font>21</font><span class="month">октября</span><span class="month">2026</span></span>')
        self.assertEqual(starts, date(2026, 10, 21))
        self.assertIsNone(ends)

    def test_vsesibir_informatics_registration_keeps_opening_and_closing_days(self):
        starts, ends, _ = self.parse('<span class="main_date"><font>19...6</font><span class="month">октября</span><span class="month">ноября</span><span class="month">2026</span></span>')
        self.assertEqual(starts, date(2026, 10, 19))
        self.assertEqual(ends, date(2026, 11, 6))

    def test_same_month_range(self):
        starts, ends, _ = self.parse('<span class="main_date"><font>1 - 19</font><span class="month">февраля</span><span class="month">2027</span></span>')
        self.assertEqual(starts, date(2027, 2, 1))
        self.assertEqual(ends, date(2027, 2, 19))

    def test_single_day_event_has_same_start_and_end(self):
        starts, ends, _ = self.parse('<span class="main_date"><font>8</font><span class="month">ноября</span><span class="month">2026</span></span>')
        self.assertEqual(starts, date(2026, 11, 8))
        self.assertEqual(ends, starts)

    def test_cross_year_range_with_one_explicit_year(self):
        starts, ends, _ = self.parse('<span class="main_date"><font>28...5</font><span class="month">декабря</span><span class="month">января</span><span class="month">2026</span></span>')
        self.assertEqual(starts, date(2026, 12, 28))
        self.assertEqual(ends, date(2027, 1, 5))

    def test_reversed_day_range_is_not_imported(self):
        starts, ends, _ = self.parse('<span class="main_date"><font>19 - 1</font><span class="month">февраля</span><span class="month">2027</span></span>')
        self.assertIsNone(starts)
        self.assertIsNone(ends)

    def test_leap_day_depends_on_calendar_year(self):
        for year, expected in [(2028, date(2028, 2, 29)), (2027, None)]:
            with self.subTest(year=year):
                starts, ends, _ = self.parse('<span class="main_date"><font>29</font><span class="month">февраля</span><span class="month">{}</span></span>'.format(year))
                self.assertEqual(starts, expected)
                self.assertEqual(ends, expected)

    def test_absent_date_node_does_not_invent_a_date(self):
        self.assertEqual(parse_date_display(None), (None, None, ''))

    def test_year_inside_font_is_not_mistaken_for_the_day(self):
        starts, ends, _ = self.parse('<span class="main_date"><font>19...6</font><span class="month">октября</span><span class="month">ноября</span><font>2026</font></span>')
        self.assertEqual(starts, date(2026, 10, 19))
        self.assertEqual(ends, date(2026, 11, 6))

    def test_catalog_of_another_season_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'сезону'):
            parse_catalog('<h1>Перечень на 2025/26</h1>', '2026/2027')

    def test_archived_event_links_are_not_current_schedule(self):
        html = '<div class="top_container"><h1>Тест по математике</h1></div><div class="events_for_activity"><a href="/activity/1/events/3?year=2025">Архив</a><a href="/activity/1/events/4">Текущий сезон</a></div>'
        result = activity_data(html, 'https://olimpiada.ru/activity/1', [{'name': 'математика'}])
        self.assertEqual(result['events'], [{'url': 'https://olimpiada.ru/activity/1/events/4', 'profile_name': 'математика'}])

    def test_previous_and_future_season_events_are_excluded(self):
        template = '<div class="content"><div class="right"><h1>Отборочный этап</h1><div class="time_classes_line_for_event"><span class="main_date"><font>8</font><span class="month">ноября</span><span class="month">{}</span></span></div></div></div>'
        for year in [2025, 2027]:
            with self.subTest(year=year):
                self.assertIsNone(event_data(template.format(year), 'https://olimpiada.ru/activity/1/events/1', 'математика', '2026/2027'))
        current = event_data(template.format(2026), 'https://olimpiada.ru/activity/1/events/1', 'математика', '2026/2027')
        self.assertEqual(current['starts_on'], date(2026, 11, 8))

    def test_invalid_concrete_event_date_fails_instead_of_replacing_known_dates(self):
        html = '<div class="content"><div class="right"><h1>Регистрация</h1><div class="time_classes_line_for_event"><span class="main_date"><font>31</font><span class="month">февраля</span><span class="month">2027</span></span></div></div></div>'
        with self.assertRaisesRegex(ValueError, 'дат'):
            event_data(html, 'https://olimpiada.ru/activity/1/events/1', 'математика', '2026/2027')

    def test_approximate_dates_from_a_previous_season_are_excluded(self):
        html = '<div class="content"><div class="right"><h1>Заключительный этап</h1><div class="time_classes_line_for_event"><span class="main_date"><span class="month">февраль 2025</span></span></div></div></div>'
        self.assertIsNone(event_data(html, 'https://olimpiada.ru/activity/1/events/1', 'математика', '2026/2027'))

    def test_declined_subject_name_matches_the_exact_approved_profile(self):
        profiles = [{'name': 'математика'}, {'name': 'информатика'}, {'name': 'история'}]
        self.assertEqual(profile_match('Олимпиада по информатике', profiles), {'name': 'информатика'})
        self.assertEqual(profile_match('Олимпиада по математике', profiles), {'name': 'математика'})

    def test_verified_editorial_alias_is_assigned_to_the_official_profile(self):
        cases = [('236', 'Межрегиональная олимпиада по информатике и компьютерной безопасности', 'компьютерная безопасность'),
                 ('5054', 'Олимпиада по гуманитарным и социальным наукам', 'гуманитарные и социальные науки'),
                 ('6', 'Олимпиада имени Эйлера', 'математика')]
        for activity_id, title, official_name in cases:
            with self.subTest(profile=official_name):
                html = '<div class="top_container"></div><div class="multiact"><div class="fav_olimp" act="{id}"><div class="o-info"><a href="/activity/{id}">{title}</a></div><div class="tl_event" ev_act="{id}" ev_id="3"></div></div></div>'.format(id=activity_id, title=title)
                result = activity_data(html, 'https://olimpiada.ru/activity/22', [{'name': official_name}])
                self.assertEqual(result['events'], [{'url': 'https://olimpiada.ru/activity/{}/events/3'.format(activity_id),
                    'profile_name': official_name}])

    def test_unsafe_registration_urls_are_rejected(self):
        for url in ['javascript:alert(1)', 'mailto:olympiad@example.org', 'https://user:password@example.org/']:
            with self.subTest(url=url):
                self.assertEqual(safe_url(url), '')

    def test_non_approved_profile_is_not_imported(self):
        html = '<div class="top_container"></div><div class="multiact"><div class="fav_olimp" act="1"><div class="o-info"><a href="/activity/1"><span class="headline">Высшая проба по истории мировых цивилизаций</span></a></div><div class="tl_event" ev_act="1" ev_id="3"></div></div></div>'
        result = activity_data(html, 'https://olimpiada.ru/activity/22', [{'name': 'история'}])
        self.assertEqual(result['events'], [])

    def test_registration_button_does_not_link_to_news_article(self):
        soup = BeautifulSoup('<a href="/media/news/open">Открыта регистрация участников на олимпиаду</a><a href="https://portal.example/">Личный кабинет</a>', 'html.parser')
        self.assertEqual(registration_link(soup, 'https://organizer.example/', generic=True), 'https://portal.example/')

    def test_subject_specific_registration_does_not_replace_common_portal(self):
        soup = BeautifulSoup('<a href="https://special.example/">Регистрация на промышленное программирование</a><a href="https://common.example/">Личный кабинет</a>', 'html.parser')
        self.assertEqual(registration_link(soup, 'https://organizer.example/', generic=True), 'https://common.example/')

    def test_ambiguous_registration_form_is_not_guessed(self):
        soup = BeautifulSoup('<a href="https://first.example/">Регистрация</a><a href="https://second.example/">Регистрация</a>', 'html.parser')
        self.assertEqual(registration_link(soup, 'https://organizer.example/'), '')

    def test_profile_registration_form_is_assigned_only_to_its_profile(self):
        soup = BeautifulSoup('<a href="https://special.example/">Регистрация на промышленное программирование</a>', 'html.parser')
        result = profile_registration_links(soup, 'https://organizer.example/',
            [{'name': 'промышленное программирование'}, {'name': 'математика'}])
        self.assertEqual(result, {'промышленное программирование': 'https://special.example/'})


class SeleniumSourceSafetyTests(SimpleTestCase):
    """Fake WebDriver responses exercise failures without opening a real browser."""

    def setUp(self):
        from .services.browser import SeleniumSource
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = SeleniumSource.__new__(SeleniumSource)
        self.source.timeout = 1
        self.source.delay = 0
        self.source.cache = {}
        self.source.cache_dir = Path(self.directory.name)
        self.source.use_cache = False
        self.source.page_count = 0
        self.source.driver = MagicMock()
        self.source.driver.current_url = 'https://organizer.example/schedule/'
        self.source.driver.find_elements.return_value = []
        self.source.driver.page_source = '<html><body><div class="schedule">Даты</div></body></html>'

    def test_chrome_network_error_document_is_not_cached_as_a_successful_page(self):
        self.source.driver.current_url = 'chrome-error://chromewebdata/'
        with patch('olympiads.services.browser.WebDriverWait'):
            with self.assertRaisesRegex(RuntimeError, 'ошибки сети'):
                self.source.get('https://organizer.example/schedule/', retries=1)
        self.assertEqual(self.source.cache, {})
        self.assertEqual(list(self.source.cache_dir.iterdir()), [])

    def test_timeout_does_not_recover_content_from_the_wrong_page(self):
        from selenium.common.exceptions import TimeoutException
        self.source.driver.current_url = 'https://wrong.example/schedule/'
        self.source.driver.find_elements.return_value = [object()]
        with patch('olympiads.services.browser.WebDriverWait') as wait:
            wait.return_value.until.side_effect = TimeoutException('Страница не загрузилась')
            with self.assertRaises(RuntimeError):
                self.source.get('https://organizer.example/schedule/', '.schedule', retries=1)
        self.assertEqual(self.source.cache, {})

    def test_timeout_can_recover_confirmed_target_page_with_required_content(self):
        from selenium.common.exceptions import TimeoutException
        self.source.driver.find_elements.return_value = [object()]
        with patch('olympiads.services.browser.WebDriverWait') as wait:
            wait.return_value.until.side_effect = TimeoutException('Внешний ресурс не загрузился')
            result = self.source.get('https://organizer.example/schedule/', '.schedule', retries=1)
        self.assertIn('Даты', result)
        self.assertEqual(len(self.source.cache), 1)


class SyncTests(TestCase):
    def setUp(self):
        self.entry = {'number': 1, 'name': 'Тестовая олимпиада', 'official_url': 'https://organizer.example/',
                      'profiles': [{'name': 'математика', 'subjects': 'математика', 'level': 1, 'official_url': 'https://organizer.example/'}]}
        self.event = {'name': 'Регистрация', 'kind': 'registration', 'profile_name': 'математика',
                      'starts_on': date(2026, 8, 20), 'ends_on': date(2026, 9, 22), 'dates_raw': '20 августа — 22 сентября 2026',
                      'source_url': 'https://olimpiada.ru/activity/1/events/1', 'proof_url': 'https://organizer.example/', 'registration_url': ''}

    def run_sync(self, fail=False, activity=None):
        class Source:
            def get(self, url, *args, **kwargs):
                if fail and '/events/' in url:
                    raise RuntimeError('Источник временно недоступен')
                return '<html><body></body></html>'
        activity = activity if activity is not None else {'events': [{'url': self.event['source_url'], 'profile_name': 'математика'}],
                    'activities': [{'url': 'https://olimpiada.ru/activity/1', 'profile_name': 'математика', 'title': 'Тест'}], 'registration_url': ''}
        def parsed_event(html, url, profile_name, season):
            return {**self.event, 'source_url': url, 'profile_name': profile_name}
        with patch('olympiads.services.sync.parse_catalog', return_value=[self.entry]), patch('olympiads.services.sync.source_index', return_value={}), patch('olympiads.services.sync.source_urls', return_value=['https://olimpiada.ru/activity/1']), patch('olympiads.services.sync.activity_data', return_value=activity), patch('olympiads.services.sync.event_data', side_effect=parsed_event):
            return sync_catalog(Source(), '2026/2027', log=lambda message: None)

    def test_repeat_sync_updates_without_duplicates(self):
        self.run_sync()
        self.event['ends_on'] = date(2026, 9, 25)
        self.run_sync()
        self.assertEqual(Olympiad.objects.count(), 1)
        self.assertEqual(OlympiadEvent.objects.count(), 1)
        self.assertEqual(OlympiadEvent.objects.get().ends_on, date(2026, 9, 25))

    def test_failed_source_keeps_last_successful_dates(self):
        self.run_sync()
        run = self.run_sync(fail=True)
        self.assertEqual(run.status, 'partial')
        self.assertTrue(OlympiadEvent.objects.get().is_active)
        self.assertEqual(OlympiadEvent.objects.get().ends_on, date(2026, 9, 22))

    def test_empty_catalog_does_not_hide_existing_records(self):
        self.run_sync()
        with patch('olympiads.services.sync.parse_catalog', side_effect=ValueError('Перечень не распознан')):
            class Source:
                def get(self, *args, **kwargs):
                    return ''
            with self.assertRaises(ValueError):
                sync_catalog(Source(), '2026/2027', log=lambda message: None)
        self.assertTrue(Olympiad.objects.get().is_active)
        self.assertEqual(ScrapeRun.objects.first().status, 'failed')

    def test_same_event_url_can_belong_to_two_distinct_profiles(self):
        self.entry['profiles'].append({'name': 'информатика', 'subjects': 'информатика', 'level': 2,
                                      'official_url': 'https://organizer.example/'})
        activity = {'events': [{'url': self.event['source_url'], 'profile_name': name}
                               for name in ['математика', 'информатика']],
                    'activities': [{'url': 'https://olimpiada.ru/activity/{}'.format(index),
                                    'profile_name': name, 'title': 'Тест'}
                                   for index, name in [(1, 'математика'), (2, 'информатика')]],
                    'registration_url': ''}
        self.run_sync(activity=activity)
        self.run_sync(activity=activity)
        self.assertEqual(OlympiadEvent.objects.count(), 2)
        self.assertSetEqual(set(OlympiadEvent.objects.values_list('profile_name', flat=True)),
                            {'математика', 'информатика'})

    def test_partially_matched_profiles_keep_their_last_known_events(self):
        self.entry['profiles'].append({'name': 'информатика', 'subjects': 'информатика', 'level': 2,
                                      'official_url': 'https://organizer.example/'})
        complete = {'events': [{'url': self.event['source_url'], 'profile_name': 'математика'},
                               {'url': 'https://olimpiada.ru/activity/2/events/2', 'profile_name': 'информатика'}],
                    'activities': [{'url': 'https://olimpiada.ru/activity/1', 'profile_name': 'математика', 'title': 'Тест'},
                                   {'url': 'https://olimpiada.ru/activity/2', 'profile_name': 'информатика', 'title': 'Тест'}],
                    'registration_url': ''}
        self.run_sync(activity=complete)
        run = self.run_sync()
        self.assertEqual(run.status, 'partial')
        self.assertTrue(OlympiadEvent.objects.get(profile_name='информатика').is_active)
        self.assertTrue(Olympiad.objects.get().sync_error)

    def test_common_schedule_is_valid_for_a_multi_profile_olympiad(self):
        self.entry['profiles'].append({'name': 'информатика', 'subjects': 'информатика', 'level': 2,
                                      'official_url': 'https://organizer.example/'})
        common = {'events': [{'url': self.event['source_url'], 'profile_name': ''}],
                  'activities': [{'url': 'https://olimpiada.ru/activity/1', 'profile_name': '', 'title': 'Общее расписание'}],
                  'registration_url': ''}
        run = self.run_sync(activity=common)
        self.assertEqual(run.status, 'success')
        self.assertEqual(OlympiadEvent.objects.get().profile_name, '')

    def test_successful_refresh_deactivates_removed_events(self):
        self.run_sync()
        previous = OlympiadEvent.objects.get()
        next_url = 'https://olimpiada.ru/activity/1/events/2'
        self.run_sync(activity={'events': [{'url': next_url, 'profile_name': 'математика'}],
            'activities': [{'url': 'https://olimpiada.ru/activity/1',
                'profile_name': 'математика', 'title': 'Обновлённое расписание'}],
            'registration_url': ''})
        previous.refresh_from_db()
        self.assertFalse(previous.is_active)
        self.assertTrue(OlympiadEvent.objects.get(source_url=next_url).is_active)

    def test_refresh_does_not_deactivate_another_academic_season(self):
        previous = Olympiad.objects.create(season='2025/2026', catalog_number=1,
            name='Предыдущий сезон', catalog_url='https://rsr-olymp.ru/')
        self.run_sync()
        previous.refresh_from_db()
        self.assertTrue(previous.is_active)


class CatalogFiltersTests(TestCase):
    def setUp(self):
        self.olympiad = Olympiad.objects.create(season='2026/2027', catalog_number=1,
            name='Многопредметная олимпиада', catalog_url='https://rsr-olymp.ru/')
        self.security = OlympiadProfile.objects.create(olympiad=self.olympiad,
            name='компьютерная безопасность', subjects='информационная безопасность, информатика', level=1)
        OlympiadProfile.objects.create(olympiad=self.olympiad,
            name='история', subjects='история, обществознание', level=2)
        OlympiadProfile.objects.create(olympiad=self.olympiad,
            name='архивный профиль', subjects='архивный предмет', level=3, is_active=False)

    def test_informatics_in_subject_field_is_not_hidden(self):
        self.assertTrue(self.olympiad.has_code)
        data = filter_metadata([self.olympiad])
        self.assertIn('информатика', data['catalog_subjects'])
        self.assertIn('компьютерная безопасность', data['catalog_profiles'])

    def test_all_active_profiles_and_specific_subjects_are_available(self):
        data = filter_metadata([self.olympiad])
        self.assertEqual(data['catalog_profiles'], ['история', 'компьютерная безопасность'])
        self.assertIn('история', data['catalog_subjects'])
        self.assertIn('обществознание', data['catalog_subjects'])
        self.assertNotIn('архивный предмет', data['catalog_subjects'])

    def test_compound_agricultural_subject_is_kept_while_neighbor_subjects_are_split(self):
        compound = 'сельское, лесное и рыбное хозяйство'
        OlympiadProfile.objects.create(olympiad=self.olympiad, name='агрогенетика', level=2,
            subjects='информатика, {}, математика'.format(compound))
        data = filter_metadata([self.olympiad])
        self.assertIn(compound, data['catalog_subjects'])
        self.assertIn('информатика', data['catalog_subjects'])
        self.assertIn('математика', data['catalog_subjects'])
        self.assertNotIn('сельское', data['catalog_subjects'])
        self.assertNotIn('лесное и рыбное хозяйство', data['catalog_subjects'])
        item = next(profile for profile in data['catalog_metadata'][self.olympiad.plan_key]['profiles']
                    if profile['name'] == 'агрогенетика')
        self.assertEqual(item['subjects'], ['информатика', compound, 'математика'])

    def test_registration_dates_keep_their_profiles_for_sorting(self):
        from django.utils import timezone
        checked = timezone.now()
        OlympiadEvent.objects.create(olympiad=self.olympiad, profile=self.security,
            profile_name=self.security.name, name='Регистрация', kind='registration',
            starts_on=date(2026, 10, 19), ends_on=date(2026, 11, 6),
            source_url='https://olimpiada.ru/activity/1/events/1', last_checked_at=checked)
        data = filter_metadata([self.olympiad])['catalog_metadata'][self.olympiad.plan_key]
        self.assertEqual(data['registrations'], [{'profile': 'компьютерная безопасность',
            'name': 'Регистрация', 'starts_on': '2026-10-19', 'ends_on': '2026-11-06',
            'deadline': '2026-11-06', 'source_url': 'https://olimpiada.ru/activity/1/events/1',
            'checked_at': checked.isoformat(), 'estimated': False}])

    def test_registration_with_unknown_end_is_kept_in_metadata(self):
        from django.utils import timezone
        OlympiadEvent.objects.create(olympiad=self.olympiad, profile=self.security,
            profile_name=self.security.name, name='Начало регистрации', kind='registration',
            starts_on=date(2026, 10, 19), source_url='https://olimpiada.ru/activity/1/events/2',
            last_checked_at=timezone.now())
        rows = filter_metadata([self.olympiad])['catalog_metadata'][self.olympiad.plan_key]['registrations']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['starts_on'], '2026-10-19')
        self.assertIsNone(rows[0]['ends_on'])
        self.assertIsNone(rows[0]['deadline'])

    def test_inactive_and_non_registration_events_are_not_registration_deadlines(self):
        from django.utils import timezone
        for kind, active in [('registration', False), ('stage', True), ('other', True)]:
            OlympiadEvent.objects.create(olympiad=self.olympiad, profile=self.security,
                profile_name=self.security.name, name=kind, kind=kind, is_active=active,
                starts_on=date(2026, 10, 19), ends_on=date(2026, 11, 6),
                source_url='https://olimpiada.ru/activity/1/events/{}'.format(kind),
                last_checked_at=timezone.now())
        rows = filter_metadata([self.olympiad])['catalog_metadata'][self.olympiad.plan_key]['registrations']
        self.assertEqual(rows, [])


class CatalogRoutesTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        self.today = patch('olympiads.views.timezone.localdate', return_value=date(2026, 10, 12))
        self.today.start()
        self.addCleanup(self.today.stop)
        self.olympiad = Olympiad.objects.create(season='2026/2027', catalog_number=11,
            name='Всесибирская открытая олимпиада школьников', subjects=['информатика'],
            catalog_url='https://rsr-olymp.ru/', official_url='https://organizer.example/',
            source_url='https://olimpiada.ru/activity/11', registration_url='https://forms.example/')
        self.profile = OlympiadProfile.objects.create(olympiad=self.olympiad,
            name='информатика', subjects='информатика', level=2,
            official_url='https://organizer.example/', registration_url='https://forms.example/informatics/')
        self.event = OlympiadEvent.objects.create(olympiad=self.olympiad, profile=self.profile,
            profile_name='информатика', name='Регистрация на отборочный этап', kind='registration',
            starts_on=date(2026, 10, 19), ends_on=date(2026, 11, 6),
            source_url='https://olimpiada.ru/activity/316/events/23202', last_checked_at=timezone.now())

    def test_public_routes_are_available(self):
        for path in ['/', '/olympiads/', '/notifications/', '/study/', '/about/', '/api/olympiads/',
                     '/olympiads/{}/'.format(self.olympiad.pk)]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_detail_renders_unambiguous_russian_dates_and_registration_links(self):
        response = self.client.get('/olympiads/{}/'.format(self.olympiad.pk))
        self.assertContains(response, '19.10.2026')
        self.assertContains(response, '06.11.2026')
        self.assertContains(response, '<th>Начало</th>', html=True)
        self.assertContains(response, '<th>Окончание</th>', html=True)
        self.assertContains(response, 'href="https://forms.example/"')
        self.assertContains(response, 'href="https://forms.example/informatics/"')

    def test_api_preserves_both_dates_and_exact_profile(self):
        data = self.client.get('/api/olympiads/').json()
        self.assertEqual(data['count'], 1)
        row = data['olympiads'][0]
        self.assertEqual(row['events'][0]['starts_on'], '2026-10-19')
        self.assertEqual(row['events'][0]['ends_on'], '2026-11-06')
        self.assertEqual(row['events'][0]['profile'], 'информатика')
        self.assertEqual(row['profiles'][0]['registration_url'], 'https://forms.example/informatics/')

    def test_catalog_does_not_include_previous_season_or_inactive_olympiads(self):
        Olympiad.objects.create(season='2025/2026', catalog_number=11,
            name='Предыдущий сезон', catalog_url='https://rsr-olymp.ru/')
        Olympiad.objects.create(season='2026/2027', catalog_number=12, is_active=False,
            name='Исключена из перечня', catalog_url='https://rsr-olymp.ru/')
        data = self.client.get('/api/olympiads/').json()
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['olympiads'][0]['id'], self.olympiad.pk)

    def test_unknown_olympiad_is_a_clear_404(self):
        self.assertEqual(self.client.get('/olympiads/999999/').status_code, 404)

    def test_unpublished_start_date_is_shown_as_unknown(self):
        self.event.starts_on = None
        self.event.save(update_fields=['starts_on'])
        response = self.client.get('/olympiads/{}/'.format(self.olympiad.pk))
        self.assertContains(response, 'Не опубликовано')
        self.assertContains(response, '06.11.2026')

    def test_start_only_source_text_is_not_shown_as_the_closing_date(self):
        self.event.starts_on = date(2026, 10, 21)
        self.event.ends_on = None
        self.event.dates_raw = 'С 21 октября 2026'
        self.event.save(update_fields=['starts_on', 'ends_on', 'dates_raw'])
        response = self.client.get('/olympiads/{}/'.format(self.olympiad.pk))
        soup = BeautifulSoup(response.content, 'html.parser')
        row = soup.select_one('.schedule-table tbody tr')
        columns = row.find_all('td', recursive=False)
        self.assertIn('21.10.2026', columns[2].get_text(' ', strip=True))
        self.assertEqual(columns[3].get_text(' ', strip=True), 'Не опубликовано')
        self.assertNotIn('С 21 октября', columns[3].get_text(' ', strip=True))
        self.assertContains(response, 'С 21 октября 2026')

    def test_partial_refresh_warns_that_the_schedule_may_be_outdated(self):
        self.olympiad.sync_error = 'Источник временно недоступен'
        self.olympiad.save(update_fields=['sync_error'])
        response = self.client.get('/olympiads/{}/'.format(self.olympiad.pk))
        self.assertContains(response, 'Последнее обновление расписания прошло не полностью')
