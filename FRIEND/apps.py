from django.apps import AppConfig


class FriendConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'FRIEND'

    def ready(self):
        # Import signal receivers here when they are added to FRIEND/receivers.py
        pass  # noqa: F401
