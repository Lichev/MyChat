from django.apps import AppConfig


class ChatRoomsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'CHAT_ROOMS'

    def ready(self):
        # Import signal receivers here when they are added to CHAT_ROOMS/receivers.py
        pass  # noqa: F401
