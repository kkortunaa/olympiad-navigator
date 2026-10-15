from django.urls import include, path
from olympiads import views as olympiad_views

urlpatterns = [
    path('', include('classrooms.urls')),
    path('', include('planner.urls')),
    path('olympiads/<int:pk>/', olympiad_views.detail, name='olympiad_detail'),
    path('api/olympiads/', olympiad_views.catalog_api, name='olympiads_api'),
    path('', include('homepage.urls')),
    path('sunc/', include('sunc.urls')),
    path('about/', include('about.urls')),
]
