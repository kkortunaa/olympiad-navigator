from django.urls import path
from . import views

urlpatterns = [
    path('', views.sunc, name='sunc'),
]
