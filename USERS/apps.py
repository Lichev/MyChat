from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'USERS'

    def ready(self):
        # Import signal receivers here when they are added to USERS/receivers.py
        pass  # noqa: F401
