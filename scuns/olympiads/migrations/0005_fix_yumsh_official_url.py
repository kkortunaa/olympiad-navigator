from django.db import migrations


def fix_yumsh_url(apps, schema_editor):
    old_urls = [scheme + host + slash
                for scheme in ('http://', 'https://')
                for host in ('yumsh.spbu.ru', 'www.yumsh.spbu.ru')
                for slash in ('', '/')]
    for name in ('Olympiad', 'OlympiadProfile'):
        model = apps.get_model('olympiads', name)
        model.objects.using(schema_editor.connection.alias).filter(
            official_url__in=old_urls).update(official_url='https://yumsh.ru/cms/yumsh-olymp')


class Migration(migrations.Migration):
    dependencies = [('olympiads', '0004_event_venues')]
    operations = [migrations.RunPython(fix_yumsh_url, migrations.RunPython.noop)]
