from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'USERS'

    def ready(self):
        # H7: register signal receivers that maintain the UserSession denorm table.
        import USERS.signals  # noqa: F401
