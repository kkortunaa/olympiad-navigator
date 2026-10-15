from django.urls import path
from . import views

app_name = 'planner'
urlpatterns = [
    path('teacher/signup/', views.signup, {'role': 'teacher'}, name='teacher_signup'),
    path('teacher/login/', views.signin, {'role': 'teacher'}, name='teacher_login'),
    path('signup/', views.signup, name='signup'),
    path('login/', views.signin, name='login'),
    path('logout/', views.signout, name='logout'),
    path('account/', views.account, name='account'),
    path('account/password/', views.password, name='password'),
    path('api/workspace/', views.workspace_api, name='workspace_api'),
]
