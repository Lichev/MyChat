from django.contrib import admin
from .models import (
    PublicChatRoom, Message, MessageReply,
    MessageAttachment, MessageEditLog, MessageDeletionLog,
)


@admin.register(PublicChatRoom)
class PublicChatRoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'creator', 'is_private', 'for_friends_only')
    search_fields = ('name',)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('room', 'sender', 'timestamp')
    list_filter = ('room',)
    raw_id_fields = ('sender', 'room')


@admin.register(MessageReply)
class MessageReplyAdmin(admin.ModelAdmin):
    list_display = ('message', 'sender', 'timestamp')
    raw_id_fields = ('message', 'sender')


admin.site.register(MessageAttachment)
admin.site.register(MessageEditLog)
admin.site.register(MessageDeletionLog)
