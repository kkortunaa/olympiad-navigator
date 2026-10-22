from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from olympiads import views as olympiad_views

urlpatterns = [
    path('', include('practice.urls')),
    path('', include('classrooms.urls')),
    path('', include('planner.urls')),
    path('olympiads/<int:pk>/', olympiad_views.detail, name='olympiad_detail'),
    path('api/olympiads/', olympiad_views.catalog_api, name='olympiads_api'),
    path('', include('homepage.urls')),
    path('sunc/', include('sunc.urls')),
    path('about/', include('about.urls')),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
