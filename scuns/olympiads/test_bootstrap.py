from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from .models import Olympiad, OlympiadEvent, OlympiadProfile


class BootstrapCatalogTests(TestCase):
    def test_public_snapshot_loads_without_accounts_and_is_idempotent(self):
        output = StringIO()
        call_command('bootstrap_catalog', stdout=output)
        self.assertEqual(Olympiad.objects.count(), 60)
        self.assertEqual(OlympiadProfile.objects.count(), 272)
        self.assertEqual(OlympiadEvent.objects.count(), 397)
        self.assertEqual(get_user_model().objects.count(), 0)
        first = Olympiad.objects.first()
        first.name = 'Изменённое название'
        first.save()
        call_command('bootstrap_catalog', stdout=output)
        first.refresh_from_db()
        self.assertEqual(first.name, 'Изменённое название')
        self.assertEqual(Olympiad.objects.count(), 60)

    def test_existing_catalog_is_never_overwritten(self):
        olympiad = Olympiad.objects.create(season='2027/2028', catalog_number=1,
                                          name='Моя олимпиада', catalog_url='https://example.test')
        call_command('bootstrap_catalog', stdout=StringIO())
        self.assertEqual(list(Olympiad.objects.values_list('pk', flat=True)), [olympiad.pk])
