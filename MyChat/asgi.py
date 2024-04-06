import os

from django.core.asgi import get_asgi_application

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
import  CHAT_ROOMS.routing


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'MyChat.settings')

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        'websocket': AuthMiddlewareStack(
            URLRouter(CHAT_ROOMS.routing.websocket_urlpatterns)
        )
    }
)
