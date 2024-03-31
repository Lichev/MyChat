from django.contrib.auth import forms as auth_forms, get_user_model
from django import forms


UserModel = get_user_model()


class RegisterUserForm(auth_forms.UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = UserModel
        fields = ('username', 'email', 'password1', 'password2', 'first_name', 'last_name')


class ProfileSettingsNameForm(forms.ModelForm):
    class Meta:
        model = UserModel
        fields = ('first_name', 'last_name')


class ProfileSettingsAvatarForm(forms.ModelForm):
    class Meta:
        model = UserModel
        fields = ['profile_picture']

    def __init__(self, *args, **kwargs):
        super(ProfileSettingsAvatarForm, self).__init__(*args, **kwargs)
        self.fields['profile_picture'].widget.attrs.update({'class': 'primary-btn'})
