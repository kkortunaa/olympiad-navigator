"""Load the public catalog for a new installation, without personal data."""
from pathlib import Path

from django.core.management import BaseCommand, call_command
from django.db import transaction

from olympiads.models import Olympiad


class Command(BaseCommand):
    help = 'Заполнить пустой каталог сохранёнными открытыми данными олимпиад.'

    @transaction.atomic
    def handle(self, *args, **options):
        if Olympiad.objects.exists():
            self.stdout.write('Каталог уже заполнен. Существующие данные сохранены.')
            return
        fixture = Path(__file__).resolve().parents[2] / 'fixtures' / 'catalog_2026_2027.json'
        call_command('loaddata', str(fixture), verbosity=0)
        self.stdout.write(self.style.SUCCESS(
            f'Загружен публичный каталог: {Olympiad.objects.count()} олимпиад. '
            'Аккаунты и классы создаются самостоятельно.'))
