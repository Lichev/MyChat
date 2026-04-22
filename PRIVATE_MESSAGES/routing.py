from django.urls import re_path

from .consumers import PrivateMessageConsumer

websocket_urlpatterns = [
    re_path(r"^ws/pm/(?P<user_id>\d+)/$", PrivateMessageConsumer.as_asgi()),
]
