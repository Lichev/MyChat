import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MyChat.settings')

from django.core.asgi import get_asgi_application

# Must be called before any project imports so Django's app registry is ready.
django_asgi_app = get_asgi_application()

from django.conf import settings
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
import CHAT_ROOMS.routing

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        'websocket': AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                URLRouter(CHAT_ROOMS.routing.websocket_urlpatterns)
            )
        )
    }
)

if settings.DEBUG:
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
    application = ASGIStaticFilesHandler(application)
