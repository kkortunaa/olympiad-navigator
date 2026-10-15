import hashlib
from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from olympiads.models import OlympiadProfile
from olympiads.services.browser import SeleniumSource
from olympiads.services.parsing import task_archive_link


class Command(BaseCommand):
    help = 'Находит опубликованные ссылки на архивы заданий по профилям. Старые ссылки при ошибках сохраняются.'

    def add_arguments(self, parser):
        parser.add_argument('--cached-only', action='store_true', help='Читать только ранее сохранённые страницы Selenium, без сетевых запросов.')
        parser.add_argument('--driver-path')
        parser.add_argument('--chrome-binary')
        parser.add_argument('--only-missing', action='store_true')
        parser.add_argument('--timeout', type=int, default=12)

    def handle(self, *args, **options):
        source = None
        saved, absent, errors = 0, 0, 0
        try:
            if not options['cached_only']:
                source = SeleniumSource(driver_path=options['driver_path'], binary=options['chrome_binary'], timeout=options['timeout'], delay=0.1)
            queryset = OlympiadProfile.objects.filter(is_active=True, olympiad__is_active=True).select_related('olympiad')
            if options['only_missing']:
                queryset = queryset.filter(tasks_url='')
            for index, profile in enumerate(queryset, 1):
                try:
                    source_url = profile.source_url or profile.olympiad.source_url
                    if not source_url:
                        absent += 1
                        continue
                    if options['cached_only']:
                        path = settings.BASE_DIR.parent / '.scraper-cache' / (hashlib.sha256(source_url.encode()).hexdigest() + '.html')
                        if not path.exists():
                            absent += 1
                            continue
                        html = path.read_text(encoding='utf-8')
                        checked = datetime.fromtimestamp(path.stat().st_mtime, tz=dt_timezone.utc)
                    else:
                        html = source.get(source_url, '.top_container')
                        checked = timezone.now()
                    url = task_archive_link(html, source_url)
                    if url:
                        profile.tasks_url, profile.tasks_checked_at = url, checked
                        profile.save(update_fields=['tasks_url', 'tasks_checked_at'])
                        saved += 1
                    else:
                        absent += 1
                except Exception as exc:
                    errors += 1
                    self.stderr.write('{}: {}'.format(profile.name, exc))
                if index % 20 == 0:
                    self.stdout.write('Профилей обработано: {}. Ссылок сохранено: {}.'.format(index, saved))
                    self.stdout.flush()
        finally:
            if source:
                source.close()
        self.stdout.write('Ссылок сохранено: {}. Без опубликованной ссылки/страницы: {}. Ошибок: {}.'.format(saved, absent, errors))
