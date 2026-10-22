from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone

from classrooms.models import SchoolNotice
from classrooms.services import notice
from planner.models import Workspace
from planner.state import MAX_ACTIVITY
from .grading import is_correct
from .models import AssignedQuestion, Attempt, AttemptAnswer, PaperAssignment, Recipient


class WorkConflict(Exception):
    pass


@transaction.atomic
def give_paper(variant, form):
    items = list(variant.items.select_related('question'))
    if not items or len(items) > 50:
        raise ValidationError('Добавьте в вариант от 1 до 50 заданий.')
    if any(item.question.author_id != variant.classroom.teacher_id for item in items):
        raise ValidationError('Вариант содержит чужое задание.')
    # Validate even if an author edited the record outside the normal form.
    for item in items:
        item.question.full_clean()
    classroom = form.cleaned_data['classroom']
    if classroom.teacher_id != variant.classroom.teacher_id:
        raise ValidationError('Чужой класс недоступен.')
    members = classroom.memberships.filter(is_active=True).select_related('student')
    if form.cleaned_data['audience'] == 'selected':
        members = members.filter(pk__in=form.cleaned_data['students'].values_list('pk', flat=True))
    members = list(members)
    if not members:
        raise ValidationError('В классе нет выбранных активных учеников.')
    assignment = form.save(commit=False)
    assignment.variant = variant
    assignment.title, assignment.instructions = variant.title, variant.notes
    assignment.save()
    AssignedQuestion.objects.bulk_create([AssignedQuestion(assignment=assignment, source_question=item.question,
        position=index, points=item.points, data=item.question.snapshot()) for index, item in enumerate(items, 1)])
    for member in members:
        recipient = Recipient.objects.create(assignment=assignment, membership=member)
        notice(member.student, classroom, 'Новый вариант от преподавателя', assignment.title,
               reverse('practice:work', args=[recipient.pk]), 'variant', member)
    return assignment


@transaction.atomic
def start_attempt(recipient):
    # Acquire a write lock before reading state, including on SQLite (where
    # select_for_update alone does not serialize concurrent browser requests).
    Recipient.objects.filter(pk=recipient.pk).update(attempts_started=F('attempts_started'))
    recipient = Recipient.objects.select_related('assignment').get(pk=recipient.pk)
    if recipient.assignment.closed:
        raise ValidationError('Срок выполнения варианта закончился.')
    current = recipient.attempts.filter(status='progress').first()
    if current:
        return current
    updated = Recipient.objects.filter(pk=recipient.pk, attempts_started__lt=recipient.assignment.max_attempts).update(
        attempts_started=F('attempts_started') + 1)
    if not updated:
        raise ValidationError('Все разрешённые попытки уже использованы.')
    recipient.refresh_from_db(fields=['attempts_started'])
    attempt = Attempt.objects.create(recipient=recipient, number=recipient.attempts_started)
    AttemptAnswer.objects.bulk_create([AttemptAnswer(attempt=attempt, question=q) for q in recipient.assignment.questions.all()])
    return attempt


def feedback_visible(assignment, attempt, answer=None):
    if assignment.feedback_mode == 'deadline':
        return assignment.closed and attempt.status == 'submitted'
    if assignment.feedback_mode == 'immediate' and answer is not None:
        return answer.checked_at is not None
    return attempt.status == 'submitted'


def solution_visible(assignment, attempt, answer):
    return assignment.show_solutions and feedback_visible(assignment, attempt, answer)


def score(attempt):
    responses = list(attempt.answers.all())
    total = sum(answer.question.points for answer in responses)
    earned = sum(answer.question.points for answer in responses if answer.is_correct is True)
    return {'earned': earned, 'total': total, 'percent': round(earned * 100 / total) if total else 0,
            'correct': sum(answer.is_correct is True for answer in responses), 'count': len(responses)}


def _complete(attempt, answers):
    now = timezone.now()
    for answer in answers:
        answer.is_correct = is_correct(answer.question.data, answer.value)
        answer.checked_at = now
    AttemptAnswer.objects.bulk_update(answers, ['value', 'is_correct', 'checked_at', 'saved_at'])
    attempt.status, attempt.submitted_at = 'submitted', now
    cls = attempt.recipient.assignment.classroom
    member = attempt.recipient.membership
    # Once per recipient, independently of subsequent attempts.
    first_completion = not attempt.recipient.attempts.filter(status='submitted').exclude(pk=attempt.pk).exists()
    if first_completion:
        workspace, _ = Workspace.objects.select_for_update().get_or_create(user=member.student)
        ledger = dict(workspace.state.get('activity', {}))
        if len(ledger) < MAX_ACTIVITY:
            ledger[f'practice-work-{attempt.recipient_id}'] = timezone.localdate(now).isoformat()
            workspace.state = {**workspace.state, 'activity': ledger}
            workspace.revision += 1
            workspace.save(update_fields=['state', 'revision', 'updated_at'])
        notice(cls.teacher, cls, 'Ученик завершил вариант',
               f'{member.student.get_full_name() or member.student.username}: {attempt.recipient.assignment.title}',
               reverse('practice:results', args=[attempt.recipient.assignment_id]), 'variant_result', member)
    SchoolNotice.objects.filter(recipient=member.student, kind='variant',
        url=reverse('practice:work', args=[attempt.recipient_id]), read_at__isnull=True).update(read_at=now)


@transaction.atomic
def save_sheet(attempt, revision, values, action):
    now = timezone.now()
    available = Attempt.objects.filter(pk=attempt.pk, revision=revision, status='progress').filter(
        Q(recipient__assignment__due_at__isnull=True) | Q(recipient__assignment__due_at__gt=now))
    claimed = available.update(revision=F('revision') + 1)
    attempt = Attempt.objects.select_related('recipient__assignment__classroom', 'recipient__membership__student').get(pk=attempt.pk)
    if not claimed:
        if attempt.status == 'submitted':
            if action == 'finish':
                return attempt
            raise WorkConflict('Попытка уже завершена. Откройте её результат.')
        if attempt.recipient.assignment.closed:
            raise WorkConflict('Срок закончился. Обновите страницу: сохранённые ответы будут проверены.')
        raise WorkConflict('Эта работа уже изменена в другой вкладке. Скопируйте несохранённые ответы и обновите страницу.')
    answers = list(attempt.answers.select_related('question'))
    if set(values) != {answer.question_id for answer in answers}:
        raise ValidationError('Неверный набор заданий.')
    check_id = None
    if action.startswith('check:'):
        if attempt.recipient.assignment.feedback_mode != 'immediate':
            raise ValidationError('Проверка отдельного ответа отключена преподавателем.')
        raw_id = action.split(':', 1)[1]
        check_id = int(raw_id) if raw_id.isascii() and raw_id.isdigit() and len(raw_id) < 19 else None
        if check_id not in values or not values[check_id]:
            raise ValidationError('Сначала введите ответ на выбранное задание.')
    elif action not in ('save', 'finish'):
        raise ValidationError('Неизвестное действие.')
    now = timezone.now()
    for answer in answers:
        value = values[answer.question_id]
        if value != answer.value:
            answer.is_correct, answer.checked_at = None, None
        answer.value, answer.saved_at = value, now
        if check_id == answer.question_id:
            answer.is_correct, answer.checked_at = is_correct(answer.question.data, value), now
    if action == 'finish':
        _complete(attempt, answers)
    else:
        AttemptAnswer.objects.bulk_update(answers, ['value', 'is_correct', 'checked_at', 'saved_at'])
    attempt.save(update_fields=['status', 'submitted_at', 'revision'])
    return attempt


def finalize_expired(assignment):
    if not assignment.closed:
        return
    ids = Attempt.objects.filter(recipient__assignment=assignment, status='progress').values_list('pk', flat=True)
    for pk in list(ids):
        with transaction.atomic():
            claimed = Attempt.objects.filter(pk=pk, status='progress').update(revision=F('revision') + 1)
            if claimed:
                attempt = Attempt.objects.select_related(
                    'recipient__assignment__classroom', 'recipient__membership__student').get(pk=pk)
                answers = list(attempt.answers.select_related('question'))
                _complete(attempt, answers)
                attempt.save(update_fields=['status', 'submitted_at', 'revision'])


def topic_statistics(answers):
    topics, mistakes = defaultdict(lambda: {'count': 0, 'wrong': 0}), []
    for answer in answers:
        if answer.is_correct is None:
            continue
        data = answer.question.data
        group = topics[(data['subject'], data['topic'])]
        group['count'] += 1
        if not answer.is_correct:
            group['wrong'] += 1
            mistakes.append(answer)
    rows = [{'subject': subject, 'topic': topic, **values,
             'percent': round(100 * (values['count'] - values['wrong']) / values['count'])}
            for (subject, topic), values in topics.items()]
    return sorted(rows, key=lambda row: (-row['wrong'], row['subject'], row['topic'])), mistakes
