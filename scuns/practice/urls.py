from django.urls import path
from . import views

app_name = 'practice'
urlpatterns = [
    path('teacher/questions/', views.questions, name='questions'),
    path('teacher/questions/new/', views.question_edit, name='question_new'),
    path('teacher/questions/<int:pk>/', views.question_edit, name='question_edit'),
    path('teacher/questions/<int:pk>/archive/', views.question_archive, name='question_archive'),
    path('teacher/variants/<int:pk>/items/', views.paper_item, name='paper_item'),
    path('teacher/variants/<int:pk>/give/', views.paper_give, name='give'),
    path('teacher/works/<int:pk>/results/', views.results, name='results'),
    path('practice/', views.student_works, name='student_works'),
    path('practice/statistics/', views.statistics, name='statistics'),
    path('practice/works/<int:pk>/', views.work, name='work'),
    path('practice/works/<int:pk>/start/', views.attempt_start, name='start'),
    path('practice/attempts/<int:pk>/', views.attempt_detail, name='attempt'),
    path('practice/attempts/<int:pk>/save/', views.attempt_save, name='save'),
    path('practice/attempts/<int:pk>/questions/<int:question_pk>/explain/', views.explanation, name='explain'),
]
