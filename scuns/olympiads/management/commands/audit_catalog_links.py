"""Check stored public links without treating access restrictions as dead pages."""
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from django.core.management.base import BaseCommand
from django.utils import timezone as django_timezone

from olympiads.models import CatalogLinkCheck, Olympiad, OlympiadEvent, OlympiadProfile


def check_link(url, timeout, retry_timeout=True):
    result = {'url': url}
    try:
        parts = urlsplit(url)
        wire_url = urlunsplit((parts.scheme, parts.netloc.encode('idna').decode('ascii'),
                              quote(parts.path, safe='/%:@'), quote(parts.query, safe='=&%/:?@+'), ''))
        request = Request(wire_url, headers={'User-Agent': 'Mozilla/5.0 (compatible; OlympTrack link check)',
                                        'Accept': 'text/html,*/*;q=0.8'})
        with urlopen(request, timeout=timeout) as response:
            body = response.read(131072).decode('utf-8', errors='replace')
            title = re.search(r'<title[^>]*>(.*?)</title>', body, re.I | re.S)
            result.update(status=response.status, final_url=response.geturl(),
                          title=re.sub(r'\s+', ' ', title.group(1)).strip() if title else '',
                          outcome='reachable')
            if title and re.search(r'404|страница не найдена|page not found|домен продается',
                                   title.group(1), re.I):
                result['outcome'] = 'needs_review'
            elif title and re.search(r'временно недоступ|temporarily unavailable|service unavailable',
                                     title.group(1), re.I):
                result['outcome'] = 'temporarily_unavailable'
            elif re.match(r'^/(admin|administrator)(/|$)', parts.path, re.I):
                result['outcome'] = 'needs_review'
    except HTTPError as error:
        result.update(status=error.code, final_url=error.geturl(),
                      outcome='not_found' if error.code in (404, 410) else 'access_or_server_error')
    except (URLError, OSError, ValueError) as error:
        result.update(outcome='connection_error', error=str(error))
        if retry_timeout and ('timed out' in str(error).lower() or 'timeout' in str(error).lower()):
            return check_link(url, max(timeout, 20), retry_timeout=False)
    return result


class Command(BaseCommand):
    help = 'Проверить ссылки; --save-checks сохраняет статусы для выбора рабочих переходов.'

    def add_arguments(self, parser):
        parser.add_argument('--report', required=True)
        parser.add_argument('--workers', type=int, default=6)
        parser.add_argument('--timeout', type=float, default=12)
        parser.add_argument('--save-checks', action='store_true',
                            help='Сохранить результаты для выбора рабочих ссылок в интерфейсе.')

    def handle(self, *args, **options):
        owners = {}
        for model in (Olympiad, OlympiadProfile, OlympiadEvent):
            fields = [f.name for f in model._meta.fields if f.name.endswith('_url')]
            for item in model.objects.filter(is_active=True).values('pk', 'name', *fields):
                for field in fields:
                    url = item[field]
                    if url:
                        owners.setdefault(url, []).append({
                            'model': model._meta.label_lower, 'pk': item['pk'],
                            'name': item['name'], 'field': field})
        report = Path(options['report'])
        report.parent.mkdir(parents=True, exist_ok=True)
        results = []

        def save():
            data = {'checked_at': datetime.now(timezone.utc).isoformat(),
                    'total_urls': len(owners), 'checked_urls': len(results),
                    'results': sorted(results, key=lambda row: row['url'])}
            temporary = report.with_suffix(report.suffix + '.tmp')
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(report)

        self.stdout.write(f'Уникальных ссылок: {len(owners)}', ending='\n')
        with ThreadPoolExecutor(max_workers=max(1, min(options['workers'], 12))) as pool:
            futures = {pool.submit(check_link, url, options['timeout']): url for url in owners}
            for future in as_completed(futures):
                result = future.result()
                result['owners'] = owners[result['url']]
                if options['save_checks']:
                    # 403/429 can mean bot restrictions, not a broken page.
                    outcome = ('restricted' if result.get('status') in (403, 429)
                               else result['outcome'])
                    CatalogLinkCheck.objects.update_or_create(url=result['url'], defaults={
                        'outcome': outcome, 'status_code': result.get('status'),
                        'error': result.get('error', '')[:2000], 'checked_at': django_timezone.now()})
                results.append(result)
                if len(results) % 25 == 0:
                    save()
                    self.stdout.write(f'Проверено {len(results)}/{len(owners)}')
        save()
        self.stdout.write(self.style.SUCCESS(f'Отчёт сохранён: {report}'))
