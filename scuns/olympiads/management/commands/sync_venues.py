"""Refresh stage venues independently of registration dates and personal data."""
import hashlib
import json
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from olympiads.models import OlympiadEvent
from olympiads.services.browser import SeleniumSource
from olympiads.services.venues import event_venue_data, activity_venue_data, merge_venue_data


class Command(BaseCommand):
    help = 'Собрать места и форматы туров через Selenium, сохраняя ссылки и подтверждения.'

    def add_arguments(self, parser):
        parser.add_argument('--season')
        parser.add_argument('--driver-path')
        parser.add_argument('--event-ids', type=int, nargs='+', help='Обновить только указанные записи туров.')
        parser.add_argument('--timeout', type=int, default=12)
        parser.add_argument('--cached-only', action='store_true', help='Разобрать сохранённые страницы без сетевых запросов.')
        parser.add_argument('--report', default='venue-sync-report.json')

    def handle(self, *args, **options):
        today=timezone.localdate(); year=today.year if today.month>=8 else today.year-1
        season=options['season'] or '{}/{}'.format(year,year+1)
        if options['timeout']<1:
            raise CommandError('Ожидание страницы должно быть положительным.')
        report={'started_at':timezone.now().isoformat(),'season':season,'cached_only':options['cached_only'],
                'stages':0,'saved':0,'with_format':0,'with_venue':0,'with_venue_link':0,'unconfirmed':0,'errors':[]}
        source=None; pages={}
        def read(url, selector):
            if url in pages:
                return pages[url]
            if options['cached_only']:
                path=settings.BASE_DIR.parent/'.scraper-cache'/(hashlib.sha256(url.encode()).hexdigest()+'.html')
                result=(path.read_text(encoding='utf-8'),datetime.fromtimestamp(path.stat().st_mtime,tz=dt_timezone.utc))
            else:
                result=(source.get(url,selector,retries=1),timezone.now())
            pages[url]=result
            return result
        try:
            if not options['cached_only']:
                source=SeleniumSource(driver_path=options['driver_path'],timeout=options['timeout'],delay=0.1)
            events=OlympiadEvent.objects.filter(is_active=True,kind='stage',olympiad__is_active=True,olympiad__season=season).select_related('olympiad').order_by('olympiad__catalog_number','profile_name','starts_on')
            if options['event_ids']:
                events=events.filter(pk__in=options['event_ids'])
            total=events.count()
            for index,event in enumerate(events,1):
                report['stages']+=1; data={}; checked=None
                try:
                    html,checked=read(event.source_url,'.time_classes_line_for_event')
                    data=event_venue_data(html,event.name,event.source_url)
                except Exception as exc:
                    report['errors'].append({'event':event.pk,'url':event.source_url,'error':str(exc)})
                if not data or not (data.get('venue') or data.get('venue_url')):
                    activity_url=event.source_url.split('/events/',1)[0]
                    try:
                        html,checked=read(activity_url,'.top_container')
                        description=activity_venue_data(html,event.name,activity_url,season)
                        combined=merge_venue_data(data,description)
                        if combined and combined.get('venue_source_url')==activity_url:
                            data=combined
                        elif data:
                            checked=pages[event.source_url][1]
                    except Exception as exc:
                        report['errors'].append({'event':event.pk,'url':activity_url,'error':str(exc)})
                        if event.venue or event.venue_url:
                            # A format-only event page cannot erase a known address when its source failed.
                            data={}
                if data:
                    OlympiadEvent.objects.filter(pk=event.pk).update(**data,venue_checked_at=checked)
                    report['saved']+=1
                    report['with_format']+=bool(data['participation_format'])
                    report['with_venue']+=bool(data['venue'])
                    report['with_venue_link']+=bool(data['venue_url'])
                else:
                    # Empty/failed reads do not erase previously known venue facts.
                    report['unconfirmed']+=1
                if index%15==0 or index==total:
                    self.stdout.write('{}/{} туров. Место/формат получены: {}. Описаний площадки: {}. Ошибок: {}.'.format(index,total,report['saved'],report['with_venue'],len(report['errors'])))
                    self.stdout.flush()
        finally:
            if source:
                source.close()
            report['finished_at']=timezone.now().isoformat();report['pages']=len(pages)
            Path(options['report']).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        self.stdout.write('Готово: {} туров, сведения сохранены для {}, описание площадки для {}, ссылок на площадки {}. Без подтверждения: {}. Ошибок: {}.'.format(report['stages'],report['saved'],report['with_venue'],report['with_venue_link'],report['unconfirmed'],len(report['errors'])))
