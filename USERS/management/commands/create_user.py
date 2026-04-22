import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

UserModel = get_user_model()


class Command(BaseCommand):
    help = "Create a user ready to log in immediately."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Username")
        parser.add_argument("--first-name", help="First name")
        parser.add_argument("--last-name", help="Last name")
        parser.add_argument("--password", help="Password (prompted if omitted)")
        parser.add_argument("--superuser", action="store_true", help="Grant superuser/staff/admin flags")

    def handle(self, *args, **options):
        username = options["username"] or input("Username: ")
        first_name = options["first_name"] or input("First name: ")
        last_name = options["last_name"] or input("Last name: ")
        password = options["password"] or getpass.getpass("Password: ")

        if UserModel.objects.filter(username=username).exists():
            raise CommandError(f"Username '{username}' is already taken.")

        user = UserModel(
            username=username,
            first_name=first_name,
            last_name=last_name,
        )

        if options["superuser"]:
            user.is_staff = True
            user.is_superuser = True

        user.set_password(password)

        try:
            user.full_clean()
        except Exception as e:
            raise CommandError(f"Validation error: {e}")

        user.save()

        label = "Superuser" if options["superuser"] else "User"
        self.stdout.write(self.style.SUCCESS(f"{label} '{username}' created — ready to log in."))
