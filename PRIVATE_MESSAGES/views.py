"""
PRIVATE_MESSAGES views.

Endpoints:
    GET  /pm/chat/<peer_id>/       — conversation_view (HTML shell for E2EE chat)
    POST /pm/panic-wipe/           — panic_wipe_view
    POST /pm/register-identity/    — register_identity_view
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
from .consumers import _MAX_KEY_FIELD_LEN, _MAX_OTPK_BATCH, _MAX_SPK_SIG_LEN
from .services import (
    publish_one_time_prekeys,
    register_identity,
    wipe_all_pm_data_for,
)

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
        # Conversation mode: Users panel is active; Rooms tab becomes a hub link.
        "active_tab":        "conversation",
        "current_peer_id":   peer.id,
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


@login_required
@require_POST
def register_identity_view(request):
    """
    POST /pm/register-identity/

    Atomically register an identity key, signed prekey, and an initial batch
    of one-time prekeys for the authenticated user in a single HTTP call.

    This endpoint exists to close the bootstrap gap on the hub page, where no
    WebSocket is open yet and the client needs to publish its own keys before
    any peer can initiate a session.

    Idempotency
    -----------
    Safe to call multiple times. ``register_identity`` wipes the previous OTPK
    pool and signed prekeys before writing the new identity, so re-publishing
    the same key material is silent and results in exactly one IdentityKey row
    and one SignedPreKey row. The alarm-suppression logic (``is_rotation``
    detection) in Phase 1 ensures identical re-publishes do not produce spurious
    peer notifications.

    No friendship gate
    ------------------
    The user publishes their OWN keys; there is no peer to authorise against.

    No peer broadcast
    -----------------
    This endpoint is called from the hub-level bootstrap, before any specific
    peer is targeted. ``register_identity`` still computes ``is_rotation``
    internally, but this view discards it and does NOT send ``pm_key_rotate_alarm``
    to anyone. If the user later runs a WebSocket ``key.rotate`` that performs a
    genuine rotation, that consumer path still sends the alarm correctly.

    Security
    --------
    - @login_required: rejects anonymous requests with a redirect.
    - @require_POST: rejects GET/HEAD/PUT/etc.
    - CSRF: enforced by Django's CsrfViewMiddleware (do NOT add @csrf_exempt).
    - All writes committed atomically; any failure rolls back entirely.
    - Validation mirrors the bounds used by PrivateMessageConsumer handlers.
    """
    user_id = request.user.id

    # --- Parse JSON body ---------------------------------------------------
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid_json"}, status=400)

    # --- Extract fields ----------------------------------------------------
    ik_pub_curve25519 = body.get("ik_pub_curve25519")
    ik_pub_ed25519 = body.get("ik_pub_ed25519")
    spk_pub = body.get("spk_pub")
    spk_sig = body.get("spk_sig")
    one_time_prekeys = body.get("one_time_prekeys")

    # --- Validate string fields --------------------------------------------
    def _bad(detail: str):
        return JsonResponse({"error": "invalid_payload", "detail": detail}, status=400)

    for field_name, value, max_len in (
        ("ik_pub_curve25519", ik_pub_curve25519, _MAX_KEY_FIELD_LEN),
        ("ik_pub_ed25519", ik_pub_ed25519, _MAX_KEY_FIELD_LEN),
        ("spk_pub", spk_pub, _MAX_KEY_FIELD_LEN),
        ("spk_sig", spk_sig, _MAX_SPK_SIG_LEN),
    ):
        if not isinstance(value, str) or not value:
            return _bad(f"{field_name} must be a non-empty string")
        if len(value) > max_len:
            return _bad(f"{field_name} exceeds maximum length of {max_len}")

    # --- Validate OTPK batch -----------------------------------------------
    if not isinstance(one_time_prekeys, list) or not one_time_prekeys:
        return _bad("one_time_prekeys must be a non-empty list")
    if len(one_time_prekeys) > _MAX_OTPK_BATCH:
        return _bad(f"one_time_prekeys exceeds maximum batch size of {_MAX_OTPK_BATCH}")

    one_time_prekeys_validated = []
    for idx, entry in enumerate(one_time_prekeys):
        if not isinstance(entry, dict):
            return _bad(f"one_time_prekeys[{idx}] must be an object")
        otpk_id = entry.get("otpk_id")
        otpk_pub = entry.get("otpk_pub")
        if not isinstance(otpk_id, str) or not otpk_id:
            return _bad(f"one_time_prekeys[{idx}].otpk_id must be a non-empty string")
        if len(otpk_id) > _MAX_KEY_FIELD_LEN:
            return _bad(f"one_time_prekeys[{idx}].otpk_id exceeds maximum length of {_MAX_KEY_FIELD_LEN}")
        if not isinstance(otpk_pub, str) or not otpk_pub:
            return _bad(f"one_time_prekeys[{idx}].otpk_pub must be a non-empty string")
        if len(otpk_pub) > _MAX_KEY_FIELD_LEN:
            return _bad(f"one_time_prekeys[{idx}].otpk_pub exceeds maximum length of {_MAX_KEY_FIELD_LEN}")
        one_time_prekeys_validated.append({"otpk_id": otpk_id, "otpk_pub": otpk_pub})

    # --- Atomic write ------------------------------------------------------
    try:
        with transaction.atomic():
            register_identity(
                user_id=user_id,
                ik_curve=ik_pub_curve25519,
                ik_ed=ik_pub_ed25519,
                spk_pub=spk_pub,
                spk_sig=spk_sig,
            )
            count = publish_one_time_prekeys(
                user_id=user_id,
                keys=one_time_prekeys_validated,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "pm.register_identity_view_error: user_id=%s error=%s",
            user_id,
            exc,
        )
        return JsonResponse({"error": "server_error"}, status=500)

    return JsonResponse({"ok": True, "otpks_inserted": count})
