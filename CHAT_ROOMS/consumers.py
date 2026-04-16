import logging
import re

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from .models import PublicChatRoom, Message

UserModel = get_user_model()
logger = logging.getLogger(__name__)


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4003)
            return

        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = self.get_group_name(self.room_name)

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive_json(self, content, **kwargs):
        # Use the server-side authenticated user — never trust client-supplied username.
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4003)
            return

        message = content.get('message', '').strip()
        if not message:
            return

        await self.save_message(user.username, self.room_name, message)

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message,
                'username': user.username,
                'room': self.room_name,
            }
        )

    async def chat_message(self, event):
        await self.send_json({
            'message': event['message'],
            'username': event['username'],
            'room': event['room'],
        })

    @sync_to_async
    def save_message(self, username, room, message):
        try:
            user = UserModel.objects.get(username=username)
        except UserModel.DoesNotExist:
            logger.warning("save_message: unknown user %r", username)
            return
        try:
            room_obj = PublicChatRoom.objects.get(name=room)
        except PublicChatRoom.DoesNotExist:
            logger.warning("save_message: unknown room %r", room)
            return
        except PublicChatRoom.MultipleObjectsReturned:
            logger.warning("save_message: multiple rooms named %r", room)
            return

        Message.objects.create(sender=user, room=room_obj, content=message)

    def get_group_name(self, room_name):
        sanitized_room_name = re.sub(r'\W+', '_', room_name)
        return f'chat_{sanitized_room_name}'
