from django.contrib import admin
from .models import PublicChatRoom


@admin.register(PublicChatRoom)
class PublicChatRoomAdmin(admin.ModelAdmin):
    model = PublicChatRoom
    list_display = ('name', 'creator')
