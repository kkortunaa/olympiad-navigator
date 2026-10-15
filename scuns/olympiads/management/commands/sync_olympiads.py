import re
import time

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from olympiads.services.parsing import INDEX_URL


class Command(BaseCommand):
    help = 'Загрузить/обновить официальный перечень олимпиад и их расписания через Selenium.'

    def add_arguments(self, parser):
        parser.add_argument('--season', help='Учебный год, например 2026/2027. По умолчанию текущий.')
        parser.add_argument('--index-url', default=INDEX_URL, help='Подборка Олимпиада.ру для сопоставления официальных названий.')
        parser.add_argument('--limit', type=int, help='Обработать только первые N олимпиад (для проверки).')
        parser.add_argument('--timeout', type=int, default=25)
        parser.add_argument('--delay', type=float, default=0.3)
        parser.add_argument('--chrome-binary', help='Путь к Chrome, если он не найден автоматически.')
        parser.add_argument('--driver-path', help='Путь к ChromeDriver; иначе его подберет Selenium Manager.')
        parser.add_argument('--show-browser', action='store_true')
        parser.add_argument('--use-cache', action='store_true', help='Повторно использовать сохраненные страницы. Только для отладки.')
        parser.add_argument('--watch', action='store_true', help='Повторять обновление, пока команда работает.')
        parser.add_argument('--interval', type=int, default=21600, help='Интервал обновления в секундах (по умолчанию 6 часов).')

    def handle(self, *args, **options):
        now = timezone.localdate()
        year = now.year if now.month >= 8 else now.year - 1
        season = options['season'] or '{}/{}'.format(year, year + 1)
        if not re.fullmatch(r'20\d{2}/20\d{2}', season) or int(season[5:]) != int(season[:4])+1:
            raise CommandError('Формат сезона: 2026/2027.')
        if options['timeout'] < 1 or options['delay'] < 0 or (options['limit'] is not None and options['limit'] < 1):
            raise CommandError('Проверь параметры timeout, delay и limit.')
        if options['watch'] and options['interval'] < 900:
            raise CommandError('Интервал фонового обновления должен быть не меньше 900 секунд.')
        try:
            from olympiads.services.browser import SeleniumSource
            from olympiads.services.sync import sync_catalog
        except ImportError as exc:
            raise CommandError('Установи зависимости из requirements.txt: {}'.format(exc)) from exc
        def log(message):
            self.stdout.write(message)
            self.stdout.flush()

        while True:
            source = None
            try:
                source = SeleniumSource(timeout=options['timeout'], delay=options['delay'],
                    headless=not options['show_browser'], binary=options['chrome_binary'],
                    driver_path=options['driver_path'], use_cache=options['use_cache'])
                result = sync_catalog(source, season, index_url=options['index_url'],
                    limit=options['limit'], log=log)
                if result.status != 'success':
                    self.stderr.write('Обновление неполное. Замечания сохранены в журнале ScrapeRun.')
            except KeyboardInterrupt:
                self.stdout.write('Обновление остановлено.')
                return
            except Exception as exc:
                if not options['watch']:
                    raise CommandError(str(exc)) from exc
                self.stderr.write('Ошибка обновления: {}'.format(exc))
            finally:
                if source:
                    source.close()
            if not options['watch']:
                return
            self.stdout.write('Следующее обновление через {} секунд.'.format(options['interval']))
            try:
                time.sleep(options['interval'])
            except KeyboardInterrupt:
                return
