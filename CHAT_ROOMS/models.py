from django.db import models
from django.contrib.auth import get_user_model

UserModel = get_user_model()


class PublicChatRoom(models.Model):
    name = models.CharField(max_length=100)
    creator = models.ForeignKey(UserModel, on_delete=models.CASCADE, related_name='created_rooms')
    admins = models.ManyToManyField(UserModel, related_name='administered_rooms', blank=True)

    def __str__(self):
        return self.name

    def delete_room(self):
        self.delete()


class Message(models.Model):
    room = models.ForeignKey(PublicChatRoom, on_delete=models.CASCADE)
    sender = models.ForeignKey(UserModel, on_delete=models.CASCADE)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    likes = models.ManyToManyField(UserModel, related_name='liked_messages', blank=True)

    def __str__(self):
        return self.content

    def can_delete(self, user):
        return user == self.sender or user == self.room.creator or user in self.room.admins.all()

    def delete_message(self):
        # Logic to delete the message
        self.delete()


# Message Replies: Introduce the ability for users to reply to specific messages within the chat room.
class MessageReply(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='replies')
    sender = models.ForeignKey(UserModel, on_delete=models.CASCADE)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.content


# Extend the Message model to support attachments such as images, files, or multimedia content.
class MessageAttachment(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='message_attachments/')

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
# and the timestamp
class MessageDeletionLog(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='deletion_logs')
    deleter = models.ForeignKey(UserModel, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)

    # You can add additional fields here, such as reason for deletion, etc.

    def __str__(self):
        return f"{self.deleter.username} deleted message {self.message.id}"