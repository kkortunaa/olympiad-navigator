from django.urls import path
from . import views

app_name = 'homepage'

urlpatterns = [
    path('', views.homepage, name='homepage'),
    path('olympiads/', views.olympiads, name='olympiads'),
    path('plan/', views.plan, name='plan'),
    path('study/', views.study, name='study'),
    path('notifications/', views.notifications, name='notifications'),
    path('list/', views.scuns_list, name='list'),
]
