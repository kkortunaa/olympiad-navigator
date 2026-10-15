from django.shortcuts import render


def about(request):
    return render(request, 'about/index.html', {'page_title': 'О проекте'})
