from django.contrib.auth import forms as auth_forms, get_user_model
from django import forms
from .models import PublicChatRoom

UserModel = get_user_model()


class PublicChatRoomForm(forms.ModelForm):
    class Meta:
        model = PublicChatRoom
        fields = ('room_picture','name', 'is_private', 'for_friends_only',)
