"""Temporary HTTP settings for a presentation in a trusted local Wi-Fi network."""
from scuns.settings import *  # noqa: F401,F403

DEBUG = False
# The local presentation URL uses HTTP. Production settings remain unchanged.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
