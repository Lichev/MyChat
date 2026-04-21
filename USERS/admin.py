
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

UserModel = get_user_model()


@admin.register(UserModel)
class UserModelAdmin(UserAdmin):
    list_display = ('email', 'username', 'first_name', 'last_name', 'date_joined', 'last_login', 'is_active', 'is_email_verified', 'is_staff')
    search_fields = ('email', 'username', 'first_name', 'last_name')
    readonly_fields = ('id', 'date_joined', 'last_login')

    fieldsets = UserAdmin.fieldsets + (
        ('Profile', {'fields': ('gender', 'profile_picture', 'phone_number', 'date_of_birth', 'country', 'city', 'bio', 'interests', 'hide_email')}),
        ('Verification', {'fields': ('is_email_verified',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'first_name', 'last_name', 'password1', 'password2'),
        }),
    )

    def save_model(self, request, obj, form, change):
        """Users created via admin are verified immediately."""
        if not change:
            obj.is_email_verified = True
        super().save_model(request, obj, form, change)
