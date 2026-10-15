import json
import hashlib

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.db import transaction
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.cache import never_cache
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import ProfileForm, SignupForm, RoleAuthenticationForm
from .models import Workspace
from .state import clean_state, MAX_WORKSPACE_BYTES


def signup(request, role='student'):
    if request.user.is_authenticated:
        return redirect('planner:account')
    form = SignupForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        user = form.save(commit=False)
        user.role = role
        user.save()
        Workspace.objects.create(user=user)
        login(request, user)
        return redirect('classrooms:teacher_home' if role == 'teacher' else 'planner:account')
    return render(request, 'planner/auth.html', {'form': form, 'page_title': 'Регистрация учителя' if role == 'teacher' else 'Регистрация ученика', 'signup': True, 'auth_teacher': role == 'teacher'})


def signin(request, role='student'):
    if request.user.is_authenticated:
        return redirect('planner:account')
    form = RoleAuthenticationForm(request, data=request.POST if request.method == 'POST' else None, role=role)
    if request.method == 'POST':
        identifier = '{}:{}'.format(request.META.get('REMOTE_ADDR', ''), request.POST.get('username', '').casefold())
        throttle = 'signin:' + hashlib.sha256(identifier.encode()).hexdigest()
        attempts = cache.get(throttle, 0)
        if attempts >= 10:
            form.add_error(None, 'Слишком много попыток входа. Попробуй снова через 5 минут.')
        elif form.is_valid():
            cache.delete(throttle)
            login(request, form.get_user())
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
            return redirect('classrooms:teacher_home' if role == 'teacher' else 'planner:account')
        else:
            cache.set(throttle, attempts + 1, timeout=300)
    return render(request, 'planner/auth.html', {'form': form, 'page_title': 'Вход для учителя' if role == 'teacher' else 'Вход для ученика', 'auth_teacher': role == 'teacher', 'next_url': request.GET.get('next', '')})


@require_POST
def signout(request):
    logout(request)
    return redirect('homepage:homepage')


@login_required
def account(request):
    form = ProfileForm(instance=request.user, data=request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Имя сохранено.')
        return redirect('planner:account')
    return render(request, 'planner/account.html', {'form': form, 'page_title': 'Личный кабинет', 'active_page': 'account'})


@login_required
def password(request):
    form = PasswordChangeForm(request.user, data=request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, 'Пароль изменён.')
        return redirect('planner:account')
    return render(request, 'planner/auth.html', {'form': form, 'page_title': 'Изменить пароль', 'password_change': True})


@require_http_methods(['GET', 'POST'])
@never_cache
def workspace_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Войди в аккаунт, чтобы сохранить изменения.'}, status=401)
    workspace, _ = Workspace.objects.get_or_create(user=request.user)
    if request.method == 'GET':
        return JsonResponse({'state': workspace.state, 'revision': workspace.revision})
    if request.content_type != 'application/json' or len(request.body) > MAX_WORKSPACE_BYTES:
        return JsonResponse({'error': 'Некорректный запрос.'}, status=400)
    try:
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or type(payload.get('revision')) is not int:
            raise ValueError('Не указана версия плана.')
        state = clean_state(payload.get('state'))
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    with transaction.atomic():
        updated = Workspace.objects.filter(user=request.user, revision=payload['revision']).update(
            state=state, revision=payload['revision'] + 1, updated_at=timezone.now())
    if not updated:
        return JsonResponse({'error': 'План изменён в другой вкладке или на другом устройстве. Сохрани копию своих изменений и загрузи свежий план.'}, status=409)
    return JsonResponse({'revision': payload['revision'] + 1})
