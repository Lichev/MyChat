import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

UserModel = get_user_model()


class Command(BaseCommand):
    help = "Create a verified user ready to log in immediately."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Username")
        parser.add_argument("--email", help="Email address")
        parser.add_argument("--first-name", help="First name")
        parser.add_argument("--last-name", help="Last name")
        parser.add_argument("--password", help="Password (prompted if omitted)")
        parser.add_argument("--superuser", action="store_true", help="Grant superuser/staff/admin flags")

    def handle(self, *args, **options):
        username = options["username"] or input("Username: ")
        email = options["email"] or input("Email: ")
        first_name = options["first_name"] or input("First name: ")
        last_name = options["last_name"] or input("Last name: ")
        password = options["password"] or getpass.getpass("Password: ")

        if UserModel.objects.filter(username=username).exists():
            raise CommandError(f"Username '{username}' is already taken.")
        if UserModel.objects.filter(email=email).exists():
            raise CommandError(f"Email '{email}' is already registered.")

        user = UserModel(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            is_email_verified=True,
        )

        if options["superuser"]:
            user.is_admin = True
            user.is_staff = True
            user.is_superuser = True

        user.set_password(password)

        try:
            user.full_clean()
        except Exception as e:
            raise CommandError(f"Validation error: {e}")

        user.save()

        label = "Superuser" if options["superuser"] else "User"
        self.stdout.write(self.style.SUCCESS(
            f"{label} '{username}' created and email verified — ready to log in."
        ))
