from django.contrib import admin
from .models import CatalogLinkCheck, Olympiad, OlympiadProfile, OlympiadEvent, ScrapeRun


@admin.register(CatalogLinkCheck)
class CatalogLinkCheckAdmin(admin.ModelAdmin):
    list_display = ['url', 'outcome', 'status_code', 'checked_at']
    list_filter = ['outcome']
    search_fields = ['url']


class ProfileInline(admin.TabularInline):
    model = OlympiadProfile
    extra = 0


@admin.register(Olympiad)
class OlympiadAdmin(admin.ModelAdmin):
    list_display = ['catalog_number', 'name', 'season', 'last_success_at', 'is_active']
    list_filter = ['season', 'is_active']
    search_fields = ['name']
    inlines = [ProfileInline]


@admin.register(OlympiadEvent)
class EventAdmin(admin.ModelAdmin):
    list_display = ['name', 'olympiad', 'profile_name', 'kind', 'starts_on', 'ends_on']
    list_filter = ['kind', 'olympiad__season']
    search_fields = ['name', 'profile_name', 'olympiad__name']


@admin.register(ScrapeRun)
class ScrapeRunAdmin(admin.ModelAdmin):
    list_display = ['started_at', 'season', 'status', 'olympiad_count', 'profile_count', 'event_count']
    readonly_fields = ['started_at', 'finished_at', 'status', 'errors', 'olympiad_count', 'profile_count', 'event_count']
