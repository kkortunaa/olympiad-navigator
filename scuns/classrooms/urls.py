from django.urls import path
from . import views

app_name = 'classrooms'
urlpatterns = [
    path('teacher/', views.teacher_home, name='teacher_home'),
    path('teacher/calendar/', views.teacher_calendar, name='teacher_calendar'),
    path('teacher/variants/', views.variants, name='variants'),
    path('teacher/classes/<int:pk>/', views.teacher_class, name='teacher_class'),
    path('teacher/classes/<int:pk>/invite/', views.invite_student, name='invite'),
    path('teacher/classes/<int:pk>/code/', views.rotate_code, name='rotate_code'),
    path('teacher/students/<int:pk>/', views.student_profile, name='student_profile'),
    path('teacher/students/<int:pk>/remove/', views.remove_student, name='remove'),
    path('teacher/classes/<int:pk>/assign/', views.assign, name='assign'),
    path('teacher/classes/<int:pk>/announce/', views.announce, name='announce'),
    path('teacher/variants/<int:pk>/', views.variant_edit, name='variant_edit'),
    path('class/', views.student_home, name='student_home'),
    path('class/join/', views.join, name='join'),
    path('class/invitations/<int:pk>/', views.invitation_answer, name='invitation_answer'),
    path('class/<int:pk>/', views.student_class, name='student_class'),
    path('class/memberships/<int:pk>/leave/', views.leave, name='leave'),
    path('class/registrations/add/', views.registration_add, name='registration_add'),
    path('class/registrations/<int:pk>/remove/', views.registration_remove, name='registration_remove'),
    path('class/assignments/<int:pk>/', views.assignment_detail, name='assignment_detail'),
    path('class/assignments/<int:pk>/answer/', views.answer, name='answer'),
    path('class/chat/<int:pk>/', views.chat, name='chat'),
    path('class/chat/<int:pk>/messages/', views.chat_api, name='chat_api'),
    path('class/notices/', views.notices_api, name='notices_api'),
    path('class/notices/read/', views.notice_read, name='notice_read'),
]
