import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse_lazy
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY environment variable is not set.")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '127.0.0.1').split(' ')

_trusted_origins = os.environ.get('CSRF_TRUSTED_ORIGINS', '')
CSRF_TRUSTED_ORIGINS = _trusted_origins.split(' ') if _trusted_origins else []

# Application definition

INSTALLED_APPS = [
    'daphne',                           # must be first for ASGI/runserver integration
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'USERS',
    'CORE',
    'FRIEND',
    'CHAT_ROOMS',
    'CHAT',
    'PRIVATE_MESSAGES',

    'channels',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'csp.middleware.CSPMiddleware',
]

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'

# HTTPS / cookie security — must be active in all non-local environments.
# DEBUG must be False in production; it is currently read from the DEBUG env var above.
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 3600  # raise to 31536000 at production go-live
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# Trusted-proxy configuration (C7 fix).
# Set SECURE_PROXY_SSL_HEADER when terminating TLS at a reverse proxy so
# Django knows the upstream scheme.  Leave None for direct / dev deployments.
# Override in production env-specific settings:
#   SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_PROXY_SSL_HEADER = None

# IPs that are allowed to set X-Forwarded-For on behalf of real clients.
# Empty by default — XFF is always ignored unless the direct peer is listed.
# Populated via environment or production settings override, e.g.:
#   TRUSTED_PROXIES = ['10.0.0.1', '10.0.0.2']
TRUSTED_PROXIES: list = []


# django-csp 4.0+ reads CONTENT_SECURITY_POLICY (dict) only. Legacy CSP_*
# tuple keys are silently ignored in 4.x — do not add them back.
# 'unsafe-inline' removed from script-src: all inline <script> blocks externalised.
# 'wasm-unsafe-eval' permits the Olm and libsodium WASM runtimes in PRIVATE_CHATS.
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src":  ["'self'", "'wasm-unsafe-eval'"],
        "style-src":   [
            "'self'",
            "'unsafe-inline'",
            "https://cdnjs.cloudflare.com",
            "https://fonts.googleapis.com",
        ],
        "font-src":    [
            "'self'",
            "https://cdnjs.cloudflare.com",
            "https://fonts.gstatic.com",
        ],
        "img-src":     ["'self'", "data:"],
        "connect-src": ["'self'", "wss:", "ws:"],
        "frame-ancestors": ["'none'"],
        "worker-src":  ["'self'"],
    }
}

ROOT_URLCONF = 'MyChat.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates']
        ,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'CHAT.context_processors.hub_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'MyChat.wsgi.application'

ASGI_APPLICATION = 'MyChat.asgi.application'

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        'NAME': os.environ.get('DB_NAME', None),
        'USER': os.environ.get('DB_USER', None),
        'PASSWORD': os.environ.get('DB_PASSWORD', None),
        'HOST': os.environ.get('DB_HOST', None),
        'PORT': os.environ.get('DB_PORT', None),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Europe/Sofia'

USE_I18N = True

USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'USERS.ChatUser'
LOGIN_REDIRECT_URL = '/chat/'
LOGOUT_REDIRECT_URL = reverse_lazy('index')

_LOG_LEVEL = os.environ.get('LOG_LEVEL', 'WARNING')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        # Belt-and-suspenders: attach PrivateChatLogScrubber to both the root
        # handler and the dedicated PRIVATE_MESSAGES logger so no ciphertext or
        # key material can leak through any handler.
        'pm_scrubber': {
            '()': 'PRIVATE_MESSAGES.logging_filters.PrivateChatLogScrubber',
        },
    },
    'handlers': {
        'console': {
            'level': _LOG_LEVEL,
            'class': 'logging.StreamHandler',
            # Scrubber on the root handler catches all loggers that propagate.
            'filters': ['pm_scrubber'],
        },
    },
    'root': {
        'handlers': ['console'],
        'level': _LOG_LEVEL,
    },
    'loggers': {
        # Dedicated PRIVATE_MESSAGES logger with its own scrubber reference.
        # propagate=False prevents double-handling via the root logger's handler;
        # the scrubber filter here is redundant with the root handler's filter
        # but provides defence-in-depth if the handler list changes.
        'PRIVATE_MESSAGES': {
            'handlers': ['console'],
            'level': _LOG_LEVEL,
            'propagate': False,
            'filters': ['pm_scrubber'],
        },
        'django.channels': {
            'handlers': ['console'],
            'level': _LOG_LEVEL,
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['console'],
            'level': _LOG_LEVEL,
            'propagate': False,
        },
    },
}


REDIS_URL = os.environ.get('REDIS_URL', None)

if REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [REDIS_URL],
            },
        }
    }
else:
    # InMemoryChannelLayer is only suitable for single-process development.
    # Set REDIS_URL in production.
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }



# EMAIL CONFIG
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_FROM_USER = os.environ.get('EMAIL_FROM_USER', None)
EMAIL_HOST = os.environ.get('EMAIL_HOST', None)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', None)
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', None)
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
