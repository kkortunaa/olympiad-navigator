from django.conf import settings
from django.db import models


def empty_workspace():
    return {'tasks': [], 'activity': {}, 'favorites': [], 'participation': {},
            'preferences': {'notifications': True, 'lead_days': 3}, 'dismissed': []}


class Workspace(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='workspace')
    state = models.JSONField(default=empty_workspace)
    revision = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
