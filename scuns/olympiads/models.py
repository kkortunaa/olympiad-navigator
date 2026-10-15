from django.db import models
from django.utils import timezone


class Olympiad(models.Model):
    season = models.CharField('Учебный год', max_length=9, db_index=True)
    catalog_number = models.PositiveSmallIntegerField('Номер в перечне')
    name = models.CharField('Название', max_length=600)
    official_url = models.URLField('Сайт организатора', max_length=1000, blank=True)
    source_url = models.URLField('Карточка Олимпиада.ру', max_length=1000, blank=True)
    catalog_url = models.URLField('Источник перечня', max_length=1000)
    registration_url = models.URLField('Страница регистрации', max_length=1000, blank=True)
    subjects = models.JSONField('Профили', default=list)
    is_active = models.BooleanField(default=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    sync_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['catalog_number']
        unique_together = [('season', 'catalog_number')]
        verbose_name = 'Олимпиада'
        verbose_name_plural = 'Олимпиады'

    def __str__(self):
        return self.name

    @property
    def plan_key(self):
        return 'olymp-{}-{}'.format(self.season[:4], self.catalog_number)

    @property
    def card_deadline(self):
        dates = [event.ends_on for event in self.events.all()
                 if event.is_active and event.kind == 'registration' and event.ends_on]
        upcoming = [day for day in dates if day >= timezone.localdate()]
        return min(upcoming) if upcoming else None

    @property
    def card_events(self):
        return [event for event in self.events.all() if event.is_active and event.kind in ('registration', 'stage')][:4]

    @property
    def has_math(self):
        return any('математ' in (profile.name + ' ' + profile.subjects).lower()
                   for profile in self.profiles.all() if profile.is_active)

    @property
    def has_code(self):
        return any('информат' in (profile.name + ' ' + profile.subjects).lower()
                   for profile in self.profiles.all() if profile.is_active)


class OlympiadProfile(models.Model):
    olympiad = models.ForeignKey(Olympiad, related_name='profiles', on_delete=models.CASCADE)
    name = models.CharField(max_length=600)
    subjects = models.TextField(blank=True)
    level = models.PositiveSmallIntegerField()
    official_url = models.URLField(max_length=1000, blank=True)
    source_url = models.URLField(max_length=1000, blank=True)
    registration_url = models.URLField(max_length=1000, blank=True)
    is_active = models.BooleanField(default=True)
    tasks_url = models.URLField('Архив заданий', max_length=1000, blank=True)
    tasks_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']
        unique_together = [('olympiad', 'name')]

    def __str__(self):
        return self.name


class OlympiadEvent(models.Model):
    olympiad = models.ForeignKey(Olympiad, related_name='events', on_delete=models.CASCADE)
    profile = models.ForeignKey(OlympiadProfile, related_name='events', on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=600)
    profile_name = models.CharField(max_length=600, blank=True)
    kind = models.CharField(max_length=20, choices=[('registration', 'Регистрация'), ('stage', 'Тур'), ('other', 'Другое')])
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True, db_index=True)
    dates_raw = models.CharField(max_length=600, blank=True)
    source_url = models.URLField(max_length=1000)
    proof_url = models.URLField(max_length=1000, blank=True)
    registration_url = models.URLField(max_length=1000, blank=True)
    participation_format = models.CharField('Формат тура', max_length=16, blank=True, choices=[
        ('online', 'Дистанционно'), ('remote', 'Заочно'), ('offline', 'Очно'), ('hybrid', 'Очно или дистанционно')])
    venue = models.TextField('Место проведения', blank=True)
    venue_url = models.URLField('Список площадок', max_length=1000, blank=True)
    venue_source_url = models.URLField('Источник места проведения', max_length=1000, blank=True)
    venue_note = models.TextField('Подтверждение места и формата', blank=True)
    venue_basis = models.CharField('Тип источника места', max_length=16, blank=True)
    venue_checked_at = models.DateTimeField('Проверка места', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    last_checked_at = models.DateTimeField()

    class Meta:
        ordering = ['starts_on', 'profile_name', 'name']
        unique_together = [('olympiad', 'source_url', 'profile_name')]


class ScrapeRun(models.Model):
    season = models.CharField(max_length=9)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    status = models.CharField(max_length=20, default='running')
    olympiad_count = models.PositiveIntegerField(default=0)
    profile_count = models.PositiveIntegerField(default=0)
    event_count = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list)

    class Meta:
        ordering = ['-started_at']
