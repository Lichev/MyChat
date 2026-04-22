from django.conf import settings
from django.db import models
from django.contrib.auth import get_user_model

UserModel = get_user_model()


def get_room_picture(instance, filename):
    ext = filename.rsplit('.', 1)[-1]
    return f'room_images/{instance.pk}/room_picture.{ext}'


def get_default_room_picture():
    return 'default_profile.png'


class PublicChatRoom(models.Model):
    name = models.CharField(max_length=100, unique=True)
    creator = models.ForeignKey(UserModel, on_delete=models.CASCADE, related_name='created_rooms')
    admins = models.ManyToManyField(UserModel, related_name='administered_rooms', blank=True)
    is_private = models.BooleanField(default=False)
    for_friends_only = models.BooleanField(default=False)
    members = models.ManyToManyField(UserModel, related_name='group_members', blank=True)

    room_picture = models.ImageField(
        max_length=255,
        upload_to=get_room_picture,
        null=True,
        blank=True,
        default=get_default_room_picture,
    )

    class Meta:
        verbose_name = 'Public Chat Room'
        verbose_name_plural = 'Public Chat Rooms'
        ordering = ['name']

    def __str__(self):
        return self.name

    def is_admin(self, user):
        """Check if the user is an admin of the room."""
        return self.admins.filter(pk=user.id).exists() or self.creator == user



class Message(models.Model):
    room = models.ForeignKey(PublicChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(UserModel, on_delete=models.CASCADE, related_name='sent_messages')
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    likes = models.ManyToManyField(UserModel, related_name='liked_messages', blank=True)

    class Meta:
        ordering = ('timestamp',)

    def __str__(self):
        return self.content

    def can_delete(self, user):
        return (
            user == self.sender
            or user == self.room.creator
            or self.room.admins.filter(pk=user.pk).exists()
        )


# Message Replies: Introduce the ability for users to reply to specific messages within the chat room.
class MessageReply(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='replies')
    sender = models.ForeignKey(UserModel, on_delete=models.CASCADE)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.content


def attachment_upload_to(instance, filename):
    """
    Shard attachment storage by year/month/room to avoid flat-directory
    hotspots.  Returns:  attachments/<yyyy>/<mm>/<room_id>/<uuid32>.<ext>

    Changing upload_to from a string to a callable does NOT require a DB
    migration — Django stores the per-instance path in the FileField column,
    so old records (under media/message_attachments/) continue to resolve
    correctly while new uploads use the sharded layout.
    """
    import os
    import uuid
    from django.utils import timezone as _tz

    ext = os.path.splitext(filename)[1].lower()
    now = _tz.now()
    room_id = getattr(instance.message, 'room_id', 'orphan')
    return f'attachments/{now:%Y/%m}/{room_id}/{uuid.uuid4().hex}{ext}'


# Extend the Message model to support attachments such as images, files, or multimedia content.
class MessageAttachment(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to=attachment_upload_to)

    # You can add additional fields here, such as description, file type, etc.

    def __str__(self):
        return self.file.name


# Message Edits: Allow users to edit their own messages within a certain time window. This involves adding a field to
# track the edit history of messages and implementing logic to enforce editing restrictions.
class MessageEditLog(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='edit_logs')
    editor = models.ForeignKey(UserModel, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)

    # You can add additional fields here, such as the edited content, reason for edit, etc.

    def __str__(self):
        return f"{self.editor.username} edited message {self.message.id}"


# Message Deletion Logs: Enhance message deletion functionality by logging deletion events. This involves creating a
# separate model to store deletion logs, including information about the deleted message, the user who deleted it,
# and the timestamp.
#
# H5 fix: changed message FK to SET_NULL so the audit row survives when the
# message itself is deleted — previously CASCADE destroyed the audit record
# at the exact moment it mattered most. Denormalised snapshot fields preserve
# the original message identity, sender, and room even after the message row
# is gone, keeping the audit trail meaningful.
class MessageDeletionLog(models.Model):
    # SET_NULL so deleting the message row does NOT cascade-delete the audit row.
    message = models.ForeignKey(
        Message,
        on_delete=models.SET_NULL,
        null=True,
        related_name='deletion_logs',
    )
    deleter = models.ForeignKey(UserModel, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)

    # Denormalised snapshot fields — written at create time and never mutated.
    # These preserve audit information after the message FK is nulled out.
    message_id_snapshot = models.PositiveIntegerField(
        db_index=True,
        help_text="Original message PK, preserved after message deletion.",
    )
    message_sender_snapshot = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='+',
        help_text="Original message sender, preserved after message deletion.",
    )
    message_room_snapshot = models.ForeignKey(
        'PublicChatRoom',
        on_delete=models.SET_NULL,
        null=True,
        related_name='+',
        help_text="Room the message was in, preserved after message deletion.",
    )

    def __str__(self):
        return (
            f"{self.deleter.username} deleted message {self.message_id_snapshot}"
        )
