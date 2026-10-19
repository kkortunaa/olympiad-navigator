from django.db import migrations


# Frozen verified addresses: do not import the changing runtime correction map.
REPLACEMENTS = {
    'http://abiturient.tsu.ru/ru/content/ormo': 'https://info.abiturient.tsu.ru/ru/content/ormo',
    'https://abiturient.tsu.ru/ru/content/ormo': 'https://info.abiturient.tsu.ru/ru/content/ormo',
    'http://ntcontest.ru': 'https://ntcontest.ru/',
    'http://www.olympiads.ru/zaoch': 'https://inf-open.ru/',
    'https://www.olympiads.ru/zaoch': 'https://inf-open.ru/',
    'http://olympiads.ru/zaoch': 'https://inf-open.ru/',
    'https://olympiads.ru/zaoch': 'https://inf-open.ru/',
}


def update_organizers(apps, schema_editor):
    for name in ('Olympiad', 'OlympiadProfile'):
        model = apps.get_model('olympiads', name)
        for old, new in REPLACEMENTS.items():
            model.objects.using(schema_editor.connection.alias).filter(
                official_url__in=(old, old + '/')).update(official_url=new)


class Migration(migrations.Migration):
    dependencies = [('olympiads', '0005_fix_yumsh_official_url')]
    operations = [migrations.RunPython(update_organizers, migrations.RunPython.noop)]
