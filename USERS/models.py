import os
import unicodedata
from enum import Enum

from django.contrib.auth.base_user import BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinLengthValidator
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class MyAccountManager(BaseUserManager):

    def create_user(self, username, password=None):
        if not username:
            raise ValueError('Users must have a username.')

        user = self.model(username=username)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password):
        user = self.create_user(username=username, password=password)
        user.is_staff = True
        user.is_superuser = True
        user.save(using=self._db)
        return user


# Allowed non-letter characters in a human name (apostrophes, hyphens, spaces).
_NAME_ALLOWED_EXTRAS = {"'", "’", "-", " "}


def validate_human_name(value: str) -> None:
    """
    Accept Unicode letters, apostrophes (' and '), hyphens, and spaces.
    Reject digits, underscores, punctuation, and empty/whitespace-only strings.

    This replaces the old str.isalpha() check which rejected legitimate names
    such as "O'Neil", "Jean-Luc", "Mary Jane", and CJK characters like "李".
    """
    if not value or not value.strip():
        raise ValidationError(_("Name cannot be empty."))
    for ch in value:
        if ch in _NAME_ALLOWED_EXTRAS:
            continue
        # Unicode general category "L*" covers letters in all scripts.
        if unicodedata.category(ch).startswith("L"):
            continue
        raise ValidationError(
            _("Name may only contain letters, spaces, apostrophes, and hyphens."),
            params={"value": value},
        )


# Deprecated alias — kept so any external code importing validate_alphabetical
# continues to work without a hard error.
validate_alphabetical = validate_human_name


class ChoicesMixin:
    @classmethod
    def choices(cls):
        return [(choice.value, choice.name) for choice in cls]


class ChoicesStringMixin(ChoicesMixin):
    @classmethod
    def max_length(cls):
        return max(len(x.value) for x in cls)


class Gender(ChoicesStringMixin, Enum):
    MALE = 'male'
    FEMALE = 'female'
    DO_NOT_SHOW = 'do not show'


def get_profile_picture(self, filename):
    return f'profile_images/{self.pk}/{"profile_image.png"}'


def get_default_profile_picture():
    return 'default_profile.png'


# Create your models here.
class ChatUser(AbstractUser):
    NAME_MIN_LENGTH = 2
    NAME_MAX_LENGTH = 30

    INTEREST_CHOICES = (
        ('machine_learning', 'Machine Learning'),
        ('ai', 'Artificial Intelligence'),
        ('hiking', 'Hiking'),
        ('guitar', 'Playing Guitar'),
        # Add more interests as needed
    )

    email = None  # fully removed — no email column; apply migration step2 after Story 1.2 removes all code references

    first_name = models.CharField(
        max_length=NAME_MAX_LENGTH,
        validators=[
            MinLengthValidator(NAME_MIN_LENGTH),
            validate_human_name
        ],
        blank=False
    )

    last_name = models.CharField(
        max_length=NAME_MAX_LENGTH,
        validators=[
            MinLengthValidator(NAME_MIN_LENGTH),
            validate_human_name
        ],
        blank=False
    )

    gender = models.CharField(
        choices=Gender.choices(),
        max_length=Gender.max_length()

    )

    REQUIRED_FIELDS = []

    profile_picture = models.ImageField(
        max_length=255,
        upload_to=get_profile_picture,
        null=True,
        blank=True,
        default=get_default_profile_picture,
    )

    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
    )

    date_of_birth = models.DateField(
        blank=True,
        null=True,
    )

    recovery_key_hash = models.CharField(max_length=255, null=True, blank=True)
    recovery_key_created_at = models.DateTimeField(null=True, blank=True)

    country = models.CharField(
        max_length=100,
        blank=True, null=True
    )
    city = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    bio = models.TextField(blank=True)

    interest = models.CharField(
        max_length=50,
        choices=INTEREST_CHOICES,
        blank=True,
    )

    objects = MyAccountManager()

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    def __str__(self):
        return self.username

    def get_profile_picture_filename(self):
        if not self.profile_picture:
            return ''
        return os.path.basename(self.profile_picture.name)

    def has_perm(self, perm, obj=None):
        if self.is_active and self.is_superuser:
            return True
        return super().has_perm(perm, obj)

    def has_module_perms(self, app_label):
        return True


class UserSession(models.Model):
    """
    Denormalised mapping of live Django sessions to their owner.

    Django's default session store encodes the auth user ID inside the
    session blob, which requires decoding every active session row to find
    all sessions for a given user (O(N) scan). This table provides an O(1)
    lookup by user so that account-recovery session invalidation can be done
    with a simple FK-based DELETE rather than a full-table scan.

    Lifecycle:
    - Created by the user_logged_in signal on every successful login.
    - Deleted by the user_logged_out signal on explicit logout.
    - Cascade-deleted with the user row on account deletion.

    Note: existing live sessions at the time this table is introduced will NOT
    be backfilled — they will be evicted at their next normal logout. The
    account-recovery flow still works correctly for those sessions because
    update_session_auth_hash() rotates the session auth hash on password change,
    forcing re-authentication on any session not updated through this table.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_sessions',
    )
    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'User Session'
        verbose_name_plural = 'User Sessions'

    def __str__(self):
        return f"UserSession(user_id={self.user_id}, key={self.session_key[:8]}…)"

