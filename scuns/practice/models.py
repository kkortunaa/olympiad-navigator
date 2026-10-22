import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .grading import ANSWER_TYPES, RULES, validate_spec


def question_image_path(instance, filename):
    suffix = filename.rsplit('.', 1)[-1].lower()
    return f'practice/{uuid.uuid4().hex}.{suffix}'


class Question(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='practice_questions')
    title = models.CharField('Название', max_length=180)
    statement = models.TextField('Условие', max_length=16000)
    image = models.ImageField('Иллюстрация к условию', upload_to=question_image_path, blank=True)
    subject = models.CharField('Предмет', max_length=80)
    topic = models.CharField('Тема', max_length=120)
    difficulty = models.CharField('Сложность', max_length=12, default='medium', choices=[
        ('easy', 'Базовая'), ('medium', 'Средняя'), ('hard', 'Сложная')])
    answer_type = models.CharField('Формат ответа', max_length=12, choices=ANSWER_TYPES, default='short')
    rule = models.CharField('Правило сравнения', max_length=12, choices=RULES, default='exact')
    answers = models.JSONField(default=list)
    options = models.JSONField(default=list, blank=True)
    tolerance = models.DecimalField('Допустимая погрешность', max_digits=12, decimal_places=8, default=0,
                                    validators=[MinValueValidator(0)])
    solution = models.TextField('Объяснение решения', max_length=16000, blank=True)
    source = models.CharField('Авторство или источник', max_length=500, blank=True)
    archived = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-pk']

    def clean(self):
        validate_spec(self.answer_type, self.rule, self.answers, self.options, self.tolerance)

    def snapshot(self):
        return {'title': self.title, 'statement': self.statement, 'subject': self.subject, 'topic': self.topic,
                'difficulty': self.get_difficulty_display(), 'answer_type': self.answer_type, 'rule': self.rule,
                'answers': list(self.answers), 'options': list(self.options), 'tolerance': str(self.tolerance),
                'solution': self.solution, 'source': self.source, 'image': self.image.name if self.image else ''}

    def __str__(self):
        return self.title


class VariantItem(models.Model):
    variant = models.ForeignKey('classrooms.VariantDraft', on_delete=models.CASCADE, related_name='items')
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name='variant_items')
    position = models.PositiveSmallIntegerField()
    points = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(100)])

    class Meta:
        ordering = ['position', 'pk']
        constraints = [models.UniqueConstraint(fields=['variant', 'question'], name='practice_unique_variant_question')]


class PaperAssignment(models.Model):
    variant = models.ForeignKey('classrooms.VariantDraft', null=True, on_delete=models.SET_NULL, related_name='deliveries')
    classroom = models.ForeignKey('classrooms.Classroom', on_delete=models.CASCADE, related_name='practice_assignments')
    title = models.CharField(max_length=180)
    instructions = models.TextField(max_length=8000, blank=True)
    due_at = models.DateTimeField('Выполнить до', null=True, blank=True)
    max_attempts = models.PositiveSmallIntegerField('Число попыток', default=1,
        validators=[MinValueValidator(1), MaxValueValidator(10)])
    feedback_mode = models.CharField('Когда показывать проверку', max_length=12, default='finish', choices=[
        ('immediate', 'После проверки каждого ответа'), ('finish', 'После завершения попытки'),
        ('deadline', 'После окончания срока работы')])
    show_solutions = models.BooleanField('Показывать правильные ответы и разборы после проверки', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    @property
    def closed(self):
        return bool(self.due_at and timezone.now() >= self.due_at)

    def __str__(self):
        return self.title


class AssignedQuestion(models.Model):
    assignment = models.ForeignKey(PaperAssignment, on_delete=models.CASCADE, related_name='questions')
    source_question = models.ForeignKey(Question, null=True, on_delete=models.SET_NULL)
    position = models.PositiveSmallIntegerField()
    points = models.PositiveSmallIntegerField(default=1)
    data = models.JSONField()  # Includes reference answers. Never serialized into student pages.

    class Meta:
        ordering = ['position', 'pk']


class Recipient(models.Model):
    assignment = models.ForeignKey(PaperAssignment, on_delete=models.CASCADE, related_name='recipients')
    membership = models.ForeignKey('classrooms.Membership', on_delete=models.CASCADE, related_name='practice_works')
    attempts_started = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['assignment', 'membership'], name='practice_unique_recipient')]


class Attempt(models.Model):
    recipient = models.ForeignKey(Recipient, on_delete=models.CASCADE, related_name='attempts')
    number = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=12, default='progress', choices=[('progress', 'В работе'), ('submitted', 'Завершена')])
    revision = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['number']
        constraints = [
            models.UniqueConstraint(fields=['recipient', 'number'], name='practice_unique_attempt_number'),
            models.UniqueConstraint(fields=['recipient'], condition=models.Q(status='progress'), name='practice_one_open_attempt'),
        ]


class AttemptAnswer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(AssignedQuestion, on_delete=models.CASCADE, related_name='responses')
    value = models.TextField(max_length=2000, blank=True)
    is_correct = models.BooleanField(null=True)
    checked_at = models.DateTimeField(null=True)
    saved_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['attempt', 'question'], name='practice_unique_answer')]


class AIQuota(models.Model):
    day = models.DateField()
    scope = models.CharField(max_length=80)
    used = models.PositiveIntegerField(default=0)
    last_request_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['day', 'scope'], name='practice_unique_ai_quota')]


class AIExplanation(models.Model):
    question = models.OneToOneField(AssignedQuestion, on_delete=models.CASCADE, related_name='ai_explanation')
    digest = models.CharField(max_length=64)
    text = models.TextField(max_length=8000)
    created_at = models.DateTimeField(auto_now=True)
