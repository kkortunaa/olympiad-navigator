from datetime import datetime

from django.db import migrations


def seed_checks(apps, schema_editor):
    model = apps.get_model('olympiads', 'CatalogLinkCheck')
    urls = ['http://olymp.psu.ru/', 'https://chemolymp.narod.ru/', 'https://go.olimpsutd.ru/admin/content/profiles', 'https://inf-open.ru/', 'https://my.etude.org/groups/join/BYHPxa4D79eTjAyKyh9TDC', 'https://my.ntcontest.ru/', 'https://olympiad.gazprom.ru', 'https://olympiad.gazprom.ru/#/schedule', 'https://portal.rggu.ru/', 'https://www.pdmi.ras.ru/~olymp', 'https://www.pdmi.ras.ru/~olymp/current.html']
    for url in urls:
        model.objects.using(schema_editor.connection.alias).get_or_create(url=url, defaults={
            'outcome': 'temporarily_unavailable',
            'checked_at': datetime.fromisoformat('2026-10-19T06:21:53.779625+00:00'),
            'error': 'Не удалось подтвердить доступность при проверке каталога. Повторите audit_catalog_links --save-checks.'})


class Migration(migrations.Migration):
    dependencies = [('olympiads', '0008_cataloglinkcheck')]
    operations = [migrations.RunPython(seed_checks, migrations.RunPython.noop)]
