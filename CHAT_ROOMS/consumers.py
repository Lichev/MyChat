import logging
import re
import time

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model

from .models import PublicChatRoom, Message

UserModel = get_user_model()
logger = logging.getLogger(__name__)


_RATE_LIMIT_MESSAGES = 10   # max messages allowed
_RATE_LIMIT_WINDOW = 10     # seconds


_MAX_MESSAGE_LENGTH = 2000


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4003)
            return

        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = self.get_group_name(self.room_name)
        # Rate-limit state: timestamps of recent messages for this connection.
        self._message_timestamps = []

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

    def _is_rate_limited(self):
        """Return True if this connection has exceeded the message rate limit."""
        now = time.monotonic()
        # Evict timestamps outside the sliding window.
        self._message_timestamps = [
            t for t in self._message_timestamps if now - t < _RATE_LIMIT_WINDOW
        ]
        if len(self._message_timestamps) >= _RATE_LIMIT_MESSAGES:
            return True
        self._message_timestamps.append(now)
        return False

    async def receive_json(self, content, **kwargs):
        # Use the server-side authenticated user — never trust client-supplied username.
        user = self.scope["user"]
        if not user.is_authenticated:
            await self.close(code=4003)
            return

        if self._is_rate_limited():
            logger.warning("rate_limit: user %r exceeded message rate in room %r", user.username, self.room_name)
            await self.send_json({'error': 'Rate limit exceeded. Please slow down.'})
            return

        message_text = content.get('message', '').strip()
        if not message_text:
            return

        if len(message_text) > _MAX_MESSAGE_LENGTH:
            await self.send_json({'error': f'Message exceeds maximum length of {_MAX_MESSAGE_LENGTH} characters.'})
            return

        # Pass the already-authenticated user object directly to save_message to avoid
        # a redundant SELECT by username. The scope user was loaded by AuthMiddlewareStack
        # at handshake time and is guaranteed to be a real, persisted ChatUser instance.
        saved = await self.save_message(user, self.room_name, message_text)
        if saved is None:
            # Room lookup failed — error already logged in save_message.
            return

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message': message_text,
                'username': user.username,
                # profile_picture.url accesses the ImageField descriptor on the already-
                # loaded user instance — no extra DB query.
                'sender_avatar': user.profile_picture.url if user.profile_picture else "",
                'message_id': saved.pk,
                'timestamp': saved.timestamp.isoformat(),
                'room': self.room_name,
            }
        )

    async def chat_message(self, event):
        await self.send_json({
            'message': event['message'],
            'username': event['username'],
            'sender_avatar': event['sender_avatar'],
            'message_id': event['message_id'],
            'timestamp': event['timestamp'],
            'room': event['room'],
        })

    @sync_to_async
    def save_message(self, user, room, message):
        """Persist the message and return the created Message instance, or None on failure.

        Accepts the already-authenticated user object from scope to avoid an extra
        SELECT by username on every message.
        """
        try:
            room_obj = PublicChatRoom.objects.get(name=room)
        except PublicChatRoom.DoesNotExist:
            logger.warning("save_message: unknown room %r", room)
            return None
        except PublicChatRoom.MultipleObjectsReturned:
            logger.warning("save_message: multiple rooms named %r", room)
            return None

        return Message.objects.create(sender=user, room=room_obj, content=message)

    def get_group_name(self, room_name):
        sanitized_room_name = re.sub(r'\W+', '_', room_name)
        return f'chat_{sanitized_room_name}'
