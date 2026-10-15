from django.shortcuts import redirect, render
from olympiads.views import catalog_context


def homepage(request):
    if request.user.is_authenticated and request.user.is_teacher:
        return redirect('classrooms:teacher_home')
    return render(request, 'homepage/homepage.html', {'active_page': 'home', 'page_title': 'Твоя подготовка'})


def olympiads(request):
    return render(request, 'homepage/homepage.html', {'active_page': 'olympiads', 'page_title': 'Олимпиады', **catalog_context()})


def plan(request):
    return redirect('homepage:homepage', permanent=True)


def study(request):
    return render(request, 'homepage/homepage.html', {'active_page': 'study', 'page_title': 'Подготовка'})


def notifications(request):
    return render(request, 'homepage/homepage.html', {'active_page': 'notifications', 'page_title': 'Уведомления'})


def scuns_list(request):
    return plan(request)
