
from django.contrib import admin
from django.contrib.auth import get_user_model

# Register your models here.
UserModel = get_user_model()


@admin.register(UserModel)
class UserModelAdmin(admin.ModelAdmin):
    list_display = ('email', 'username', 'date_joined', 'last_login', 'is_active', 'is_staff')
    search_fields = ('email', 'username')
    readonly_fields = ('id', 'date_joined', 'last_login')

    filter_horizontal = ()
    list_filter = ()
    fieldsets = ()