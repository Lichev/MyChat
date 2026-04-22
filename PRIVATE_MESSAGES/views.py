"""
PRIVATE_MESSAGES views.

Endpoints:
    GET  /pm/chat/<peer_id>/   — conversation_view (HTML shell for E2EE chat)
    POST /pm/panic-wipe/       — panic_wipe_view
"""

import json
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.db import transaction
from django.views.decorators.http import require_POST

from FRIEND.models import Friend
from .services import wipe_all_pm_data_for

UserModel = get_user_model()

logger = logging.getLogger(__name__)


def _user_group(user_id: int) -> str:
    """Channel group name for a specific user (mirrors consumers.py)."""
    return f"pm_user_{user_id}"


@login_required
def conversation_view(request, peer_id: int):
    """
    GET /pm/chat/<peer_id>/

    Renders the HTML shell for an E2EE private conversation. All crypto
    is performed client-side; this view only validates the friendship gate
    and provides data islands (via json_script) for the JS modules.

    Security:
    - @login_required: rejects anonymous requests.
    - Friendship gate: 403 if not friends.
    - No message content is passed from server to template — the page is
      a static shell; messages arrive via WebSocket after client-side unlock.
    - Data passed as json_script context is non-sensitive metadata only
      (user IDs, usernames, avatar URLs). No key material is ever passed.
    """
    self_user = request.user

    # Validate peer exists.
    peer = get_object_or_404(UserModel, pk=peer_id)

    # Cannot chat with yourself.
    if peer.pk == self_user.pk:
        return HttpResponseForbidden("You cannot start a private chat with yourself.")

    # Friendship gate.
    if not Friend.objects.are_friends(self_user, peer):
        return HttpResponseForbidden(
            "You must be friends to start a private conversation."
        )

    ws_url = f"/ws/pm/{peer.id}/"

    # Context passed via json_script (type="application/json" — not executable).
    # Avatar URL: use .url to get the media path; default gracefully.
    def _avatar_url(user):
        try:
            return user.profile_picture.url
        except Exception:
            return "/static/images/default_avatar.png"

    self_ctx = {
        "user_id":    self_user.id,
        "username":   self_user.username,
        "avatar_url": _avatar_url(self_user),
    }
    peer_ctx = {
        "user_id":    peer.id,
        "username":   peer.username,
        "avatar_url": _avatar_url(peer),
    }

    return render(request, "private_chat/conversation.html", {
        # json_script context (dicts — serialised by Django's |json_script filter).
        "self_ctx":          self_ctx,
        "peer_ctx":          peer_ctx,
        "ws_url":            ws_url,
        # Template string interpolation (safe — Django auto-escapes).
        "self_username":     self_user.username,
        "self_avatar_url":   _avatar_url(self_user),
        "peer_username":     peer.username,
        "peer_avatar_url":   _avatar_url(peer),
        "peer_id":           peer.id,
        # Highlight the Users sidebar tab (hub_shell uses this to flag active tab).
        "active_tab":        "users",
    })


@login_required
@require_POST
def panic_wipe_view(request):
    """
    Atomically delete all pm_* data for the authenticated user and notify peers.

    Security checklist:
    - @login_required: rejects anonymous requests with a redirect.
    - @require_POST: rejects GET/HEAD/PUT/etc.
    - CSRF protection: enforced by Django's CsrfViewMiddleware (always active).
    - All deletions happen inside a single transaction.atomic() call inside
      wipe_all_pm_data_for — if the broadcast fails the data is still gone;
      peers will discover the wipe on their next connection attempt.
    """
    user = request.user
    user_id = user.id

    peer_ids = wipe_all_pm_data_for(user_id)

    # Broadcast pm.wipe to all peer WS groups.
    # We use async_to_sync here because views run in sync context.
    channel_layer = get_channel_layer()
    if channel_layer is not None and peer_ids:
        send = async_to_sync(channel_layer.group_send)
        for peer_id in peer_ids:
            try:
                send(
                    _user_group(peer_id),
                    {
                        "type": "pm_wipe",
                        "peer_id": user_id,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                # WS broadcast failure is non-fatal — the wipe already committed.
                logger.warning(
                    "pm.panic_wipe_broadcast_failed: user_id=%s peer_id=%s error=%s",
                    user_id,
                    peer_id,
                    exc,
                )

    logger.info(
        "pm.panic_wipe_complete: user_id=%s peers_notified=%d",
        user_id,
        len(peer_ids),
    )
    return JsonResponse({"ok": True})
