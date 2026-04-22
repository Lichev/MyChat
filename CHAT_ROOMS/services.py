from django.db.models import Max, F, OuterRef, Subquery, Q

from CHAT_ROOMS.models import PublicChatRoom, Message


def can_user_access_room(user, room) -> bool:
    """Single authoritative gate for room access.

    Returns True when the user is allowed to read/join the room.
    Checks creator, admin, and member status first (fast path).
    Falls back to privacy flags only for non-participants.
    """
    # Direct-participant fast path — one query covers all three roles.
    if room.creator_id == user.id:
        return True
    if room.admins.filter(pk=user.pk).exists():
        return True
    if room.members.filter(pk=user.pk).exists():
        return True

    # User is not a participant — evaluate privacy flags.
    if room.is_private:
        return False
    if room.for_friends_only:
        from FRIEND.models import Friend
        return Friend.objects.are_friends(user, room.creator)
    return True


def get_public_chat_rooms(user=None):
    """Return rooms ordered by latest-message timestamp.

    When *user* is provided, private rooms the user is not a
    member/admin/creator of are excluded (C2/C3 fix).
    """
    rooms_with_latest_message = PublicChatRoom.objects.annotate(
        latest_message_timestamp=Max('messages__timestamp')
    )

    if user is not None and user.is_authenticated:
        # Include a room when: not private  OR  user is creator/admin/member.
        participant_q = (
            Q(creator=user) |
            Q(admins=user) |
            Q(members=user)
        )
        rooms_with_latest_message = rooms_with_latest_message.filter(
            Q(is_private=False) | participant_q
        ).distinct()

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
