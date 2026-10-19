from django.db import migrations


def remove_obsolete_registration(apps, schema_editor):
    old_urls = [scheme + 'form.centraluniversity.ru/youth_math_olympiad' + suffix
                for scheme in ('https://', 'http://') for suffix in ('', '/')]
    for name in ('Olympiad', 'OlympiadProfile', 'OlympiadEvent'):
        model = apps.get_model('olympiads', name)
        model.objects.using(schema_editor.connection.alias).filter(
            registration_url__in=old_urls).update(registration_url='')


class Migration(migrations.Migration):
    dependencies = [('olympiads', '0006_update_verified_organizer_links')]
    operations = [migrations.RunPython(remove_obsolete_registration, migrations.RunPython.noop)]
