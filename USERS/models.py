from enum import Enum

from django.contrib.auth.base_user import BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinLengthValidator
from django.conf import settings


class MyAccountManager(BaseUserManager):

    def create_user(self, username, email, password=None):
        if not username:
            raise ValueError('Users must have a username.')
        if not email:
            raise ValueError('Users must have an email address.')

        user = self.model(
            email=self.normalize_email(email),
            username=username
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password):
        user = self.create_user(
            email=self.normalize_email(email),
            username=username,
            password=password
        )
        user.is_admin = True
        user.is_staff = True
        user.is_superuser = True
        user.save(using=self._db)
        return user


def validate_alphabetical(value):
    if not value.isalpha():
        raise ValidationError('First name should contain only alphabetical letters.')


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

    email = models.EmailField(
        unique=True,
        blank=False,
    )

    hide_email = models.BooleanField(default=True)

    first_name = models.CharField(
        max_length=NAME_MAX_LENGTH,
        validators=[
            MinLengthValidator(NAME_MIN_LENGTH),
            validate_alphabetical
        ],
        blank=False
    )

    last_name = models.CharField(
        max_length=NAME_MAX_LENGTH,
        validators=[
            MinLengthValidator(NAME_MIN_LENGTH),
            validate_alphabetical
        ],
        blank=False
    )

    gender = models.CharField(
        choices=Gender.choices(),
        max_length=Gender.max_length()

    )

    is_admin = models.BooleanField(default=False)

    profile_picture = models.ImageField(
        max_length=255,
        upload_to=get_profile_picture,
        null=True,
        blank=True,
        default=get_default_profile_picture,
    )

    phone_number = models.PositiveIntegerField(
        blank=True,
        null=True,
    )

    date_of_birth = models.DateField(
        blank=True,
        null=True,
    )

    is_email_verified = models.BooleanField(default=False)

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

    interests = models.CharField(
        max_length=20,
        choices=INTEREST_CHOICES,
        blank=True,
    )

    objects = MyAccountManager()

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    @property
    def get_mail(self):
        return {self.email}

    def __str__(self):
        return self.username

    def get_profile_picture_filename(self):
        return str(self.profile_picture)[str(self.profile_picture).index(f'profile_images/{self.pk}/'):]

    def has_perm(self, perm, obj=None):
        return self.is_admin

    def has_module_perms(self, app_label):
        return True

