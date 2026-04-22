from django.db.models import Max, F, OuterRef, Subquery

from CHAT_ROOMS.models import PublicChatRoom, Message


def get_public_chat_rooms():
    rooms_with_latest_message = PublicChatRoom.objects.annotate(
        latest_message_timestamp=Max('messages__timestamp')
    )
    return rooms_with_latest_message.order_by(
        F('latest_message_timestamp').desc(nulls_last=True)
    )


def get_last_messages_preview(rooms):
    """Return a dict {room_id: last_message_preview_str} for the given rooms queryset.

    Uses a single subquery per room — no N+1.
    The preview is truncated to 60 characters for sidebar display.
    """
    latest_message_ids = (
        Message.objects
        .filter(room=OuterRef('pk'))
        .order_by('-timestamp')
        .values('id')[:1]
    )
    rooms_with_last = rooms.annotate(last_message_id=Subquery(latest_message_ids))

    last_message_ids = [r.last_message_id for r in rooms_with_last if r.last_message_id]
    messages = (
        Message.objects
        .filter(id__in=last_message_ids)
        .select_related('sender')
    )
    msg_by_id = {m.id: m for m in messages}

    preview = {}
    for room in rooms_with_last:
        msg = msg_by_id.get(room.last_message_id)
        if msg:
            content = msg.content if len(msg.content) <= 60 else msg.content[:57] + '...'
            preview[room.id] = {
                'sender': msg.sender.username,
                'content': content,
                'timestamp': msg.timestamp.isoformat(),
            }
        else:
            preview[room.id] = None
    return preview
