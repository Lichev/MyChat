import json
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
import re

from .models import PublicChatRoom, Message

UserModel = get_user_model()


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = self.get_group_name(self.room_name)
        current_user = self.scope["user"].username

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        data = json.loads(text_data)
        message = data['message']
        username = data['username']
        room = data['room']

        await self.save_message(username, room, message)

        message_sender = username
        current_user = self.scope["user"].username  # Assuming scope["user"] holds the current user

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message,
                'username': username,
                'room': room,
                'message_sender': message_sender,
                'current_user': current_user
            }
        )

    async def chat_message(self, event):
        message = event['message']
        username = event['username']
        room = event['room']
        message_sender = event['message_sender']
        current_user = event['current_user']

        await self.send(text_data=json.dumps({
            'message': message,
            'username': username,
            'room': room,
            'message_sender': message_sender,
            'current_user': current_user
        }))

    @sync_to_async
    def save_message(self, username, room, message):
        user = UserModel.objects.get(username=username)
        room = PublicChatRoom.objects.get(name=room)

        Message.objects.create(sender=user, room=room, content=message)

    def get_group_name(self, room_name):
        sanitized_room_name = re.sub(r'\W+', '_', room_name)
        return f'chat_{sanitized_room_name}'
