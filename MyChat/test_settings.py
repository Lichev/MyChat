"""
Test-only settings override.

Points DATABASES['default']['TEST']['NAME'] at the existing 'mychat'
database so that mychat_user (which lacks CREATEDB) can run the Django
test suite without a separate test database creation step.

Usage:
    python manage.py test --settings=MyChat.test_settings PRIVATE_MESSAGES
"""

from .settings import *  # noqa: F401, F403

DATABASES["default"]["TEST"] = {  # noqa: F405
    "NAME": "mychat",
}

# Use a fast in-memory channel layer for all tests.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# Use locmem cache so rate-limit tests work without Redis.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Ensure scrubber runs at DEBUG level in log-leak tests.
import os  # noqa: E402
os.environ.setdefault("LOG_LEVEL", "DEBUG")
