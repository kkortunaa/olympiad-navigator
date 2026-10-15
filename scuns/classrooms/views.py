from functools import wraps
import hashlib

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.cache import never_cache

from olympiads.models import OlympiadProfile
from planner.models import Workspace
from planner.state import MAX_ACTIVITY
from .forms import AnswerForm, AssignmentForm, ClassroomForm, InviteForm, JoinForm, MessageForm, VariantForm
from .models import (Assignment, AssignmentReceipt, ChatMessage, Classroom, Invitation, Membership,
                     SchoolNotice, StudentRegistration, VariantDraft, invite_code)
from .services import calendar_context, notice, progress


def role_required(role):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), '/teacher/login/' if role == 'teacher' else '/login/')
            if request.user.role != role:
                raise PermissionDenied('Этот раздел доступен для другой роли аккаунта.')
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def owned_class(request, pk):
    return get_object_or_404(Classroom, pk=pk, teacher=request.user)


def chat_membership(request, pk):
    if not request.user.is_authenticated:
        raise PermissionDenied()
    member = get_object_or_404(Membership.objects.select_related('student', 'classroom__teacher'), pk=pk, is_active=True)
    if not ((request.user.is_teacher and member.classroom.teacher_id == request.user.pk) or
            (request.user.role == 'student' and member.student_id == request.user.pk)):
        raise PermissionDenied()
    return member


def member_url(member):
    return reverse('classrooms:student_profile', args=[member.pk])


def notice_queryset(user):
    return SchoolNotice.objects.filter(recipient=user).filter(Q(membership__isnull=True) | Q(membership__is_active=True))


@role_required('teacher')
def teacher_home(request):
    form = ClassroomForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        classroom = form.save(commit=False)
        classroom.teacher = request.user
        classroom.save()
        return redirect('classrooms:teacher_class', pk=classroom.pk)
    classes = request.user.teaching_classes.annotate(student_count=Count('memberships', filter=Q(memberships__is_active=True)))
    return render(request, 'classrooms/teacher_home.html', {'classes': classes, 'form': form,
                   'page_title': 'Мои классы', 'active_page': 'classes'})


@role_required('teacher')
def teacher_class(request, pk):
    cls = owned_class(request, pk)
    assignments = cls.assignments.annotate(total=Count('receipts', filter=Q(receipts__membership__is_active=True)),
        completed=Count('receipts', filter=Q(receipts__completed_at__isnull=False, receipts__membership__is_active=True)))
    return render(request, 'classrooms/teacher_class.html', {'classroom': cls,
        'members': progress(cls.memberships.filter(is_active=True)), 'invitations': cls.invitations.filter(status='pending').select_related('student'),
        'invite_form': InviteForm(), 'assignment_form': AssignmentForm(classroom=cls), 'assignments': assignments,
        'page_title': cls.name, 'active_page': 'classes'})


@role_required('teacher')
@require_POST
def invite_student(request, pk):
    cls = owned_class(request, pk)
    form = InviteForm(request.POST)
    if form.is_valid():
        student = form.student
        if cls.memberships.filter(student=student, is_active=True).exists():
            messages.info(request, 'Ученик уже в этом классе.')
        else:
            invitation, created = Invitation.objects.get_or_create(classroom=cls, student=student)
            if created or invitation.status != 'pending':
                invitation.status = 'pending'
                invitation.save(update_fields=['status'])
                notice(student, cls, 'Приглашение в класс', f'{request.user.get_full_name() or request.user.username} приглашает в {cls.name}.',
                       reverse('classrooms:student_home'), 'invitation')
            messages.success(request, 'Приглашение отправлено. Ученик подтвердит его в разделе «Мой класс».')
    else:
        messages.error(request, ' '.join(error for errors in form.errors.values() for error in errors))
    return redirect('classrooms:teacher_class', pk=pk)


@role_required('teacher')
@require_POST
def rotate_code(request, pk):
    cls = owned_class(request, pk)
    cls.code = invite_code()
    cls.save(update_fields=['code'])
    messages.success(request, 'Создан новый код класса. Старый код больше не действует.')
    return redirect('classrooms:teacher_class', pk=pk)


def activate_membership(student, cls):
    with transaction.atomic():
        member, created = Membership.objects.get_or_create(classroom=cls, student=student)
        if not member.is_active:
            member.is_active = True
            member.joined_at = timezone.now()
            member.save(update_fields=['is_active', 'joined_at'])
            created = True
        Invitation.objects.filter(classroom=cls, student=student).update(status='accepted')
        if created:
            notice(cls.teacher, cls, 'Новый ученик в классе', f'{student.get_full_name() or student.username} присоединился к {cls.name}.',
                   member_url(member), 'joined', member)
    return member


@role_required('student')
def student_home(request):
    return render(request, 'classrooms/student_home.html', {
        'memberships': request.user.class_memberships.filter(is_active=True).select_related('classroom__teacher'),
        'invitations': request.user.class_invitations.filter(status='pending').select_related('classroom__teacher'),
        'join_form': JoinForm(), 'registrations': request.user.olympiad_registrations.select_related('profile__olympiad'),
        'page_title': 'Мой класс', 'active_page': 'classes'})


@role_required('student')
@require_POST
def join(request):
    form = JoinForm(request.POST)
    throttle = 'join:' + hashlib.sha256(f'{request.user.pk}:{request.META.get("REMOTE_ADDR", "")}'.encode()).hexdigest()
    attempts = cache.get(throttle, 0)
    if attempts >= 10:
        messages.error(request, 'Слишком много неверных кодов. Попробуйте через 5 минут.')
        return redirect('classrooms:student_home')
    cls = Classroom.objects.filter(code=form.cleaned_data['code']).first() if form.is_valid() else None
    if not cls:
        cache.set(throttle, attempts + 1, 300)
        messages.error(request, 'Класс с таким кодом не найден. Уточните код у преподавателя.')
        return redirect('classrooms:student_home')
    cache.delete(throttle)
    activate_membership(request.user, cls)
    return redirect('classrooms:student_class', pk=cls.pk)


@role_required('student')
@require_POST
def invitation_answer(request, pk):
    invitation = get_object_or_404(Invitation, pk=pk, student=request.user, status='pending')
    if request.POST.get('action') in ('accept', 'decline'):
        SchoolNotice.objects.filter(recipient=request.user, classroom=invitation.classroom,
                                    kind='invitation', read_at__isnull=True).update(read_at=timezone.now())
    if request.POST.get('action') == 'accept':
        activate_membership(request.user, invitation.classroom)
        return redirect('classrooms:student_class', pk=invitation.classroom_id)
    if request.POST.get('action') == 'decline':
        invitation.status = 'declined'
        invitation.save(update_fields=['status'])
    return redirect('classrooms:student_home')


@role_required('student')
def student_class(request, pk):
    member = get_object_or_404(Membership.objects.select_related('classroom__teacher'), classroom_id=pk,
                              student=request.user, is_active=True)
    cls = member.classroom
    return render(request, 'classrooms/student_class.html', {'classroom': cls, 'membership': member,
        'members': progress(cls.memberships.filter(is_active=True)),
        'receipts': member.assignments.select_related('assignment'), 'page_title': cls.name, 'active_page': 'classes'})


@role_required('teacher')
def student_profile(request, pk):
    member = get_object_or_404(Membership.objects.select_related('student', 'classroom'), pk=pk,
                              classroom__teacher=request.user, is_active=True)
    return render(request, 'classrooms/student_profile.html', {'membership': progress(Membership.objects.filter(pk=member.pk))[0],
        'registrations': member.student.olympiad_registrations.select_related('profile__olympiad'),
        'receipts': member.assignments.select_related('assignment'),
        'page_title': member.student.get_full_name() or member.student.username, 'active_page': 'classes'})


@role_required('teacher')
@require_POST
def remove_student(request, pk):
    member = get_object_or_404(Membership, pk=pk, classroom__teacher=request.user, is_active=True)
    member.is_active = False
    member.save(update_fields=['is_active'])
    return redirect('classrooms:teacher_class', pk=member.classroom_id)


@role_required('student')
@require_POST
def leave(request, pk):
    member = get_object_or_404(Membership, pk=pk, student=request.user, is_active=True)
    member.is_active = False
    member.save(update_fields=['is_active'])
    messages.success(request, 'Вы вышли из класса. Преподавателю больше не доступен ваш профиль класса.')
    return redirect('classrooms:student_home')


@role_required('teacher')
@require_POST
def assign(request, pk):
    cls = owned_class(request, pk)
    form = AssignmentForm(request.POST, classroom=cls)
    if not form.is_valid():
        return render(request, 'classrooms/assignment_form.html', {'form': form, 'classroom': cls,
                      'page_title': 'Новое задание', 'active_page': 'classes'}, status=400)
    recipients = cls.memberships.filter(is_active=True).select_related('student')
    if form.cleaned_data['recipient'] != 'all':
        recipients = recipients.filter(pk=int(form.cleaned_data['recipient']))
    recipients = list(recipients)
    if not recipients:
        messages.error(request, 'Сначала добавьте в класс учеников.')
        return redirect('classrooms:teacher_class', pk=pk)
    with transaction.atomic():
        assignment = form.save(commit=False)
        assignment.classroom = cls
        assignment.save()
        for member in recipients:
            receipt = AssignmentReceipt.objects.create(assignment=assignment, membership=member)
            notice(member.student, cls, 'Новое задание от преподавателя', assignment.title,
                   reverse('classrooms:assignment_detail', args=[receipt.pk]), 'assignment', member)
    messages.success(request, f'Задание отправлено ученикам: {len(recipients)}.')
    return redirect('classrooms:teacher_class', pk=pk)


@role_required('student')
def assignment_detail(request, pk):
    receipt = get_object_or_404(AssignmentReceipt.objects.select_related('assignment__classroom__teacher', 'membership'),
                               pk=pk, membership__student=request.user, membership__is_active=True)
    return render(request, 'classrooms/assignment_detail.html', {'receipt': receipt,
        'form': AnswerForm(initial={'answer': receipt.answer}), 'page_title': receipt.assignment.title, 'active_page': 'classes'})


@role_required('student')
@require_POST
@transaction.atomic
def answer(request, pk):
    receipt = get_object_or_404(AssignmentReceipt.objects.select_related('assignment__classroom', 'membership'), pk=pk,
                               membership__student=request.user, membership__is_active=True)
    form = AnswerForm(request.POST)
    if not form.is_valid():
        return render(request, 'classrooms/assignment_detail.html', {'receipt': receipt, 'form': form,
            'page_title': receipt.assignment.title, 'active_page': 'classes'}, status=400)
    previously_done = receipt.completed_at is not None
    receipt.answer = form.cleaned_data['answer']
    receipt.completed_at = None if request.POST.get('action') == 'reopen' else (receipt.completed_at or timezone.now())
    receipt.save(update_fields=['answer', 'completed_at'])
    SchoolNotice.objects.filter(recipient=request.user, kind='assignment',
        url=reverse('classrooms:assignment_detail', args=[pk]), read_at__isnull=True).update(read_at=timezone.now())
    workspace, _ = Workspace.objects.select_for_update().get_or_create(user=request.user)
    ledger = dict(workspace.state.get('activity', {}))
    ledger_key = f'school-assignment-{receipt.pk}'
    if receipt.completed_at and (ledger_key in ledger or len(ledger) < MAX_ACTIVITY):
        ledger[ledger_key] = timezone.localdate(receipt.completed_at).isoformat()
    elif not receipt.completed_at:
        ledger.pop(ledger_key, None)
    workspace.state = {**workspace.state, 'activity': ledger}
    workspace.revision += 1
    workspace.save(update_fields=['state', 'revision', 'updated_at'])
    if receipt.completed_at and not previously_done:
        cls = receipt.assignment.classroom
        notice(cls.teacher, cls, 'Ученик выполнил задание',
               f'{request.user.get_full_name() or request.user.username}: {receipt.assignment.title}',
               member_url(receipt.membership), 'answer', receipt.membership)
    return redirect('classrooms:assignment_detail', pk=pk)


@role_required('student')
@require_POST
def registration_add(request):
    profile = get_object_or_404(OlympiadProfile, pk=request.POST.get('profile') if str(request.POST.get('profile', '')).isdigit() else 0,
                               is_active=True, olympiad__is_active=True)
    StudentRegistration.objects.get_or_create(student=request.user, profile=profile)
    messages.success(request, 'Запись добавлена в «Мой класс». Преподаватель увидит олимпиаду в календаре.')
    return redirect('olympiad_detail', pk=profile.olympiad_id)


@role_required('student')
@require_POST
def registration_remove(request, pk):
    get_object_or_404(StudentRegistration, pk=pk, student=request.user).delete()
    return redirect('classrooms:student_home')


@role_required('teacher')
def teacher_calendar(request):
    classes = list(request.user.teaching_classes.all())
    selected = request.GET.get('class', '')
    if selected:
        selected_class = get_object_or_404(Classroom, pk=selected if selected.isdigit() else 0, teacher=request.user)
        selected_classes = [selected_class]
    else:
        selected_classes = classes
    return render(request, 'classrooms/calendar.html', {'classes': classes, 'selected_class': selected,
        **calendar_context(selected_classes, request.GET), 'page_title': 'Календарь класса', 'active_page': 'class_calendar'})


@role_required('teacher')
def variants(request):
    classes = request.user.teaching_classes.all()
    if request.method == 'POST':
        cls = owned_class(request, request.POST.get('classroom') if str(request.POST.get('classroom', '')).isdigit() else 0)
        form = VariantForm(request.POST)
        if form.is_valid():
            draft = form.save(commit=False)
            draft.classroom = cls
            draft.save()
            return redirect('classrooms:variant_edit', pk=draft.pk)
    else:
        form = VariantForm()
    return render(request, 'classrooms/variants.html', {'classes': classes, 'form': form,
        'drafts': VariantDraft.objects.filter(classroom__teacher=request.user).select_related('classroom'),
        'page_title': 'Варианты', 'active_page': 'variants'})


@role_required('teacher')
def variant_edit(request, pk):
    draft = get_object_or_404(VariantDraft, pk=pk, classroom__teacher=request.user)
    form = VariantForm(request.POST if request.method == 'POST' else None, instance=draft)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Черновик варианта сохранён.')
        return redirect('classrooms:variant_edit', pk=pk)
    return render(request, 'classrooms/variant_edit.html', {'draft': draft, 'form': form,
        'page_title': draft.title, 'active_page': 'variants'})


@never_cache
@require_http_methods(['GET', 'POST'])
def chat(request, pk):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    member = chat_membership(request, pk)
    form = MessageForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        if message_allowed(request.user):
            send_message(request.user, member, form.cleaned_data['text'])
            return redirect('classrooms:chat', pk=pk)
        form.add_error(None, 'Слишком много сообщений. Подождите минуту.')
    items = member.chat_messages.select_related('sender')
    before = request.GET.get('before', '')
    if before.isdigit() and len(before) <= 18:
        items = items.filter(pk__lt=int(before))
    items = list(items.order_by('-pk')[:100])[::-1]
    return render(request, 'classrooms/chat.html', {'membership': member, 'chat_messages': items,
        'older': items[0].pk if items and member.chat_messages.filter(pk__lt=items[0].pk).exists() else None,
        'form': form, 'page_title': 'Чат с учеником' if request.user.is_teacher else 'Чат с преподавателем',
        'active_page': 'classes'})


def send_message(sender, member, text):
    with transaction.atomic():
        item = ChatMessage.objects.create(membership=member, sender=sender, text=text)
        recipient = member.student if sender.is_teacher else member.classroom.teacher
        notice(recipient, member.classroom, 'Новое сообщение', f'{sender.get_full_name() or sender.username}: {text[:300]}',
               reverse('classrooms:chat', args=[member.pk]), 'message', member)
    return item


def message_allowed(user):
    key = f'chat:{user.pk}'
    if cache.add(key, 1, 60):
        return True
    try:
        return cache.incr(key) <= 30
    except ValueError:
        cache.add(key, 1, 60)
        return True


@role_required('teacher')
@require_POST
@transaction.atomic
def announce(request, pk):
    cls = owned_class(request, pk)
    form = MessageForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Напишите сообщение от 1 до 4000 символов.')
    else:
        members = list(cls.memberships.filter(is_active=True).select_related('student', 'classroom__teacher'))
        for member in members:
            send_message(request.user, member, form.cleaned_data['text'])
        messages.success(request, f'Сообщение отправлено ученикам: {len(members)}.')
    return redirect('classrooms:teacher_class', pk=pk)


@never_cache
@require_http_methods(['GET', 'POST'])
def chat_api(request, pk):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Войдите в аккаунт.'}, status=401)
    member = chat_membership(request, pk)
    if request.method == 'POST':
        form = MessageForm(request.POST)
        if not form.is_valid():
            return JsonResponse({'error': 'Напишите сообщение от 1 до 4000 символов.'}, status=400)
        if not message_allowed(request.user):
            return JsonResponse({'error': 'Слишком много сообщений. Подождите минуту.'}, status=429)
        send_message(request.user, member, form.cleaned_data['text'])
        return JsonResponse({'ok': True})
    after = request.GET.get('after', '0')
    if not after.isdigit() or len(after) > 18:
        return JsonResponse({'error': 'Некорректный номер сообщения.'}, status=400)
    rows = list(member.chat_messages.filter(pk__gt=int(after)).select_related('sender').order_by('pk')[:101])
    return JsonResponse({'messages': [{'id': m.pk, 'name': m.sender.get_full_name() or m.sender.username,
        'text': m.text, 'own': m.sender_id == request.user.pk, 'time': timezone.localtime(m.created_at).strftime('%d.%m %H:%M')}
        for m in rows[:100]], 'has_more': len(rows) > 100})


@never_cache
@require_http_methods(['GET'])
def notices_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Войдите в аккаунт.'}, status=401)
    qs = notice_queryset(request.user)
    return JsonResponse({'unread': qs.filter(read_at__isnull=True).count(), 'notices': [
        {'id': n.pk, 'title': n.title, 'text': n.text, 'url': n.url, 'read': n.read_at is not None,
         'time': timezone.localtime(n.created_at).strftime('%d.%m %H:%M')} for n in qs[:50]]})


@require_POST
def notice_read(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Войдите в аккаунт.'}, status=401)
    qs = notice_queryset(request.user).filter(read_at__isnull=True)
    member_id, notice_id = request.POST.get('membership'), request.POST.get('notice')
    if member_id and member_id.isdigit():
        chat_membership(request, int(member_id))
        qs = qs.filter(membership_id=member_id, kind='message')
    elif notice_id and notice_id.isdigit():
        qs = qs.filter(pk=notice_id)
    else:
        return JsonResponse({'error': 'Укажите уведомление.'}, status=400)
    qs.update(read_at=timezone.now())
    return JsonResponse({'ok': True})
