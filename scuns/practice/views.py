from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from classrooms.models import VariantDraft
from classrooms.views import role_required
from .ai import explain
from .forms import AnswerSheetForm, GivePaperForm, ItemForm, PaperForm, QuestionForm
from .models import Attempt, AttemptAnswer, PaperAssignment, Question, Recipient, VariantItem
from .services import (WorkConflict, feedback_visible, finalize_expired, give_paper,
                       save_sheet, score, solution_visible, start_attempt, topic_statistics)


def page(request, template, context, title, status=200):
    return render(request, f'practice/{template}.html', {**context, 'page_title': title,
        'active_page': 'variants' if request.user.is_teacher else 'practice'}, status=status)


def owned_variant(user, pk):
    return get_object_or_404(VariantDraft.objects.select_related('classroom'), pk=pk, classroom__teacher=user)


def posted_id(value):
    return int(value) if value.isascii() and value.isdigit() and len(value) < 19 else 0


def own_recipient(user, pk):
    return get_object_or_404(Recipient.objects.select_related('assignment__classroom__teacher', 'membership__student'),
                            pk=pk, membership__student=user, membership__is_active=True)


@role_required('teacher')
def questions(request):
    rows = Question.objects.filter(author=request.user, archived=request.GET.get('archive') == '1')
    search = request.GET.get('q', '').strip()[:100]
    if search:
        rows = rows.filter(Q(title__icontains=search) | Q(statement__icontains=search) |
                           Q(subject__icontains=search) | Q(topic__icontains=search))
    return page(request, 'questions', {'questions': Paginator(rows, 20).get_page(request.GET.get('page')),
                                     'search': search, 'archive': request.GET.get('archive') == '1'}, 'Банк заданий')


@role_required('teacher')
def question_edit(request, pk=None):
    item = get_object_or_404(Question, pk=pk, author=request.user) if pk else Question(author=request.user)
    form = QuestionForm(request.POST or None, request.FILES or None, instance=item)
    variant_id = request.GET.get('variant', '')
    variant = owned_variant(request.user, posted_id(variant_id)) if variant_id else None
    if request.method == 'POST' and form.is_valid():
        form.save()
        if variant:
            if variant.items.count() < 50:
                VariantItem.objects.get_or_create(variant=variant, question=item,
                    defaults={'position': variant.items.count() + 1})
            return redirect('classrooms:variant_edit', pk=variant.pk)
        messages.success(request, 'Задание сохранено. Уже выданные варианты продолжают использовать прежнюю версию.')
        return redirect('practice:questions')
    return page(request, 'question_form', {'form': form, 'question': item, 'variant': variant},
                'Редактирование задания' if pk else 'Новое задание')


@role_required('teacher')
@require_POST
def question_archive(request, pk):
    question = get_object_or_404(Question, pk=pk, author=request.user)
    question.archived = not question.archived
    question.save(update_fields=['archived'])
    return redirect('practice:questions')


@role_required('teacher')
def papers(request):
    form = PaperForm(request.POST if request.method == 'POST' else None, teacher=request.user)
    if request.method == 'POST' and form.is_valid():
        draft = form.save()
        return redirect('classrooms:variant_edit', pk=draft.pk)
    return page(request, 'papers', {'form': form,
        'drafts': VariantDraft.objects.filter(classroom__teacher=request.user).select_related('classroom').annotate(item_count=Count('items')),
        'deliveries': PaperAssignment.objects.filter(classroom__teacher=request.user).select_related('classroom').annotate(recipient_count=Count('recipients'))}, 'Варианты')


@role_required('teacher')
def paper_edit(request, pk):
    variant = owned_variant(request.user, pk)
    form = PaperForm(request.POST if request.method == 'POST' else None, teacher=request.user, instance=variant)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Черновик варианта сохранён.')
        return redirect('classrooms:variant_edit', pk=pk)
    return page(request, 'paper_edit', {'draft': variant, 'form': form,
        'items': variant.items.select_related('question'),
        'item_form': ItemForm(teacher=request.user, variant=variant)}, variant.title)


@role_required('teacher')
@require_POST
@transaction.atomic
def paper_item(request, pk):
    VariantDraft.objects.filter(pk=pk, classroom__teacher=request.user).update(updated_at=timezone.now())
    variant = owned_variant(request.user, pk)
    # All builder writes serialize on the same draft.
    VariantDraft.objects.select_for_update().get(pk=variant.pk)
    action = request.POST.get('action')
    if action == 'add':
        form = ItemForm(request.POST, teacher=request.user, variant=variant)
        if form.is_valid() and variant.items.count() < 50:
            VariantItem.objects.create(variant=variant, question=form.cleaned_data['question'], points=form.cleaned_data['points'],
                                       position=variant.items.count() + 1)
        else:
            messages.error(request, 'Выберите своё задание, от 1 до 100 баллов. Максимум 50 заданий в варианте.')
    else:
        raw_id = request.POST.get('item', '')
        item = get_object_or_404(VariantItem, pk=posted_id(raw_id), variant=variant)
        items = list(variant.items.all())
        index = next(i for i, candidate in enumerate(items) if candidate.pk == item.pk)
        if action == 'remove':
            items.pop(index)
            item.delete()
        elif action in ('up', 'down'):
            target = index - 1 if action == 'up' else index + 1
            if 0 <= target < len(items):
                items[index], items[target] = items[target], items[index]
        elif action == 'points':
            raw = request.POST.get('points', '')
            if raw.isascii() and raw.isdigit() and len(raw) < 4 and 1 <= int(raw) <= 100:
                item.points = int(raw)
                item.save(update_fields=['points'])
            else:
                messages.error(request, 'Допустимо от 1 до 100 баллов.')
        else:
            return JsonResponse({'error': 'Неизвестное действие'}, status=400)
        for index, entry in enumerate(items, 1):
            entry.position = index
        VariantItem.objects.bulk_update(items, ['position'])
    return redirect('classrooms:variant_edit', pk=pk)


@role_required('teacher')
def paper_give(request, pk):
    variant = owned_variant(request.user, pk)
    selected = request.GET.get('classroom', '')
    classroom = variant.classroom
    if selected:
        classroom = get_object_or_404(request.user.teaching_classes, pk=posted_id(selected))
    form = GivePaperForm(request.POST if request.method == 'POST' else None, teacher=request.user,
                         classroom=classroom, initial={'classroom': classroom.pk})
    if request.method == 'POST' and form.is_valid():
        try:
            assignment = give_paper(variant, form)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, 'Вариант выдан. Условия и правила проверки сохранены отдельно от черновика.')
            return redirect('practice:results', pk=assignment.pk)
    return page(request, 'give', {'draft': variant, 'form': form,
        'classes': request.user.teaching_classes.all(), 'selected_classroom': classroom}, 'Выдать вариант')


@role_required('student')
def student_works(request):
    recipients = list(Recipient.objects.filter(membership__student=request.user, membership__is_active=True)
        .select_related('assignment__classroom').prefetch_related('attempts__answers__question').order_by('-assignment__created_at'))
    for recipient in recipients:
        finalize_expired(recipient.assignment)
    # Re-read after automatic deadline completion, including prefetched answers.
    recipients = list(Recipient.objects.filter(pk__in=[r.pk for r in recipients]).select_related('assignment__classroom')
                      .prefetch_related('attempts__answers__question').order_by('-assignment__created_at'))
    for recipient in recipients:
        recipient.completed = any(a.status == 'submitted' for a in recipient.attempts.all())
        recipient.current = next((a for a in recipient.attempts.all() if a.status == 'progress'), None)
    return page(request, 'student_works', {'recipients': recipients}, 'Мои варианты')


@role_required('student')
def work(request, pk):
    recipient = own_recipient(request.user, pk)
    finalize_expired(recipient.assignment)
    attempts = list(recipient.attempts.prefetch_related('answers__question'))
    for attempt in attempts:
        attempt.summary = score(attempt) if feedback_visible(recipient.assignment, attempt) else None
    return page(request, 'work', {'recipient': recipient, 'attempts': attempts,
        'current': next((a for a in attempts if a.status == 'progress'), None),
        'can_start': not recipient.assignment.closed and recipient.attempts_started < recipient.assignment.max_attempts,
        'question_count': recipient.assignment.questions.count()}, recipient.assignment.title)


@role_required('student')
@require_POST
def attempt_start(request, pk):
    recipient = own_recipient(request.user, pk)
    try:
        attempt = start_attempt(recipient)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
        return redirect('practice:work', pk=pk)
    return redirect('practice:attempt', pk=attempt.pk)


def accessible_attempt(user, pk):
    rows = Attempt.objects.select_related('recipient__assignment__classroom', 'recipient__membership__student')
    if user.is_teacher:
        rows = rows.filter(recipient__assignment__classroom__teacher=user, recipient__membership__is_active=True)
    else:
        rows = rows.filter(recipient__membership__student=user, recipient__membership__is_active=True)
    return get_object_or_404(rows, pk=pk)


@login_required
def attempt_detail(request, pk):
    attempt = accessible_attempt(request.user, pk)
    assignment = attempt.recipient.assignment
    finalize_expired(assignment)
    attempt.refresh_from_db()
    questions = list(assignment.questions.all())
    answers = {answer.question_id: answer for answer in attempt.answers.select_related('question')}
    form = AnswerSheetForm(questions=questions, saved={qid: a.value for qid, a in answers.items()}, revision=attempt.revision)
    readonly = request.user.is_teacher or attempt.status == 'submitted' or assignment.closed
    rows = []
    for question in questions:
        answer = answers.get(question.pk)
        public = {key: question.data[key] for key in ('title', 'statement', 'subject', 'topic', 'difficulty', 'source')}
        image = question.data.get('image')
        public['image_url'] = default_storage.url(image) if image else ''
        visible = request.user.is_teacher or feedback_visible(assignment, attempt, answer)
        reveal = bool(answer and (request.user.is_teacher or solution_visible(assignment, attempt, answer)))
        rows.append({'question': public, 'id': question.pk, 'position': question.position, 'points': question.points,
            'field': form[f'answer_{question.pk}'], 'value': answer.value if answer else '',
            'options': question.data['options'], 'checked': visible and answer is not None and answer.is_correct is not None,
            'correct': answer.is_correct if visible and answer else None,
            'expected': question.data['answers'] if reveal else [],
            'solution': question.data['solution'] if reveal else '', 'can_explain': reveal and not request.user.is_teacher})
    summary = score(attempt) if request.user.is_teacher or feedback_visible(assignment, attempt) else None
    return page(request, 'attempt', {'attempt': attempt, 'assignment': assignment, 'rows': rows, 'form': form,
        'readonly': readonly, 'summary': summary, 'teacher_view': request.user.is_teacher,
        'answered_count': sum(bool(a.value) for a in answers.values())}, assignment.title)


@role_required('student')
@require_POST
def attempt_save(request, pk):
    attempt = accessible_attempt(request.user, pk)
    questions = list(attempt.recipient.assignment.questions.all())
    form = AnswerSheetForm(request.POST, questions=questions, saved={})
    json_mode = 'application/json' in request.headers.get('Accept', '')
    unexpected = set(k for k in request.POST if k.startswith('answer_')) - set(form.fields)
    if unexpected or not form.is_valid():
        if json_mode:
            return JsonResponse({'error': 'Ответы не сохранены. Проверьте поля.', 'fields': form.errors}, status=400)
        messages.error(request, 'Ответы не сохранены: проверьте длину текста и выбранные варианты.')
        # Keep submitted values on validation failure rather than silently discard them.
        return page(request, 'invalid_sheet', {'form': form, 'attempt': attempt}, 'Проверьте ответы', status=400)
    try:
        updated = save_sheet(attempt, form.cleaned_data['revision'], form.values_by_question(), request.POST.get('action', 'save'))
    except (WorkConflict, ValidationError) as error:
        message = str(error) if isinstance(error, WorkConflict) else ' '.join(error.messages)
        if json_mode:
            return JsonResponse({'error': message}, status=409 if isinstance(error, WorkConflict) else 400)
        return page(request, 'invalid_sheet', {'form': form, 'attempt': attempt, 'error': message}, 'Ответы не сохранены', status=409)
    if json_mode:
        return JsonResponse({'revision': updated.revision, 'redirect': reverse('practice:attempt', args=[updated.pk])})
    messages.success(request, 'Попытка завершена.' if updated.status == 'submitted' else 'Ответы сохранены.')
    return redirect('practice:attempt', pk=pk)


@role_required('student')
@require_POST
def explanation(request, pk, question_pk):
    attempt = accessible_attempt(request.user, pk)
    answer = get_object_or_404(AttemptAnswer.objects.select_related('question'), attempt=attempt,
                              question_id=question_pk, question__assignment_id=attempt.recipient.assignment_id)
    if not solution_visible(attempt.recipient.assignment, attempt, answer):
        return JsonResponse({'error': 'Преподаватель ещё не открыл разбор этого задания.'}, status=403)
    result, status = explain(answer.question, request.user.pk)
    return JsonResponse(result, status=status)


@role_required('teacher')
def results(request, pk):
    assignment = get_object_or_404(PaperAssignment.objects.select_related('classroom'), pk=pk, classroom__teacher=request.user)
    finalize_expired(assignment)
    recipients = list(assignment.recipients.filter(membership__is_active=True).select_related('membership__student')
        .prefetch_related('attempts__answers__question'))
    all_answers, submitted_count = [], 0
    for recipient in recipients:
        attempts = list(recipient.attempts.all())
        completed = [a for a in attempts if a.status == 'submitted']
        for attempt in attempts:
            attempt.summary = score(attempt) if attempt.status == 'submitted' else None
        recipient.completed_attempts = completed
        recipient.best = max((a.summary['percent'] for a in completed), default=None)
        recipient.started = bool(attempts)
        submitted_count += bool(completed)
        all_answers.extend(answer for attempt in completed for answer in attempt.answers.all())
    topics, _ = topic_statistics(all_answers)
    by_question = defaultdict(lambda: {'total': 0, 'wrong': 0, 'students': set()})
    for answer in all_answers:
        row = by_question[answer.question_id]
        row['total'] += 1
        if answer.is_correct is False:
            row['wrong'] += 1
            row['students'].add(answer.attempt.recipient_id)
    question_stats = []
    for question in assignment.questions.all():
        values = by_question[question.pk]
        question_stats.append({'question': question, 'total': values['total'], 'wrong': values['wrong'],
                               'students': len(values['students'])})
    return page(request, 'results', {'assignment': assignment, 'recipients': recipients, 'topics': topics,
        'question_stats': question_stats, 'submitted_count': submitted_count}, f'Результаты · {assignment.title}')


@role_required('student')
def statistics(request):
    answers = AttemptAnswer.objects.filter(attempt__recipient__membership__student=request.user,
        attempt__recipient__membership__is_active=True, attempt__status='submitted').select_related(
            'question', 'attempt__recipient__assignment').order_by('-attempt__submitted_at', '-pk')
    visible = [a for a in answers if feedback_visible(a.attempt.recipient.assignment, a.attempt, a)]
    topics, mistakes = topic_statistics(visible)
    return page(request, 'statistics', {'topics': topics,
        'mistakes': Paginator(mistakes, 20).get_page(request.GET.get('page')),
        'checked_count': len(visible), 'correct_count': sum(a.is_correct is True for a in visible)}, 'Моя статистика')
