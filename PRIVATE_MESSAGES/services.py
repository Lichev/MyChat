"""
Pure service functions for PRIVATE_MESSAGES.

All functions accept primitive types (ints, strings, datetimes) and return
primitive types or model instances — no crypto-field dict blobs. This keeps
them easily unit-testable without mocking complex ORM structures.

All mutating functions are decorated with @transaction.atomic so callers
do not need to manage transactions explicitly.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from .models import (
    EncryptedEnvelope,
    IdentityKey,
    OneTimePreKey,
    PrivateSession,
    SignedPreKey,
)

logger = logging.getLogger(__name__)

# Envelopes expire after 7 days (blueprint § "DB Tables").
_ENVELOPE_TTL_DAYS = 7


# ---------------------------------------------------------------------------
# Identity key registration
# ---------------------------------------------------------------------------


@transaction.atomic
def register_identity(
    user_id: int,
    ik_curve: str,
    ik_ed: str,
    spk_pub: str,
    spk_sig: str,
) -> tuple[IdentityKey, bool]:
    """
    Create or replace the identity key and initial signed prekey for a user.

    Called once on first client setup (or on emergency IK rotation).
    Deletes any existing OTPK pool and signed prekeys for the user before
    writing the new identity to ensure a clean state.

    Parameters
    ----------
    user_id  : pk of the ChatUser
    ik_curve : Curve25519 identity key, base64url-encoded
    ik_ed    : Ed25519 identity key, base64url-encoded
    spk_pub  : Curve25519 SPK public (= ik_curve at registration), base64url
    spk_sig  : Ed25519 signature over spk_pub, base64url

    Returns
    -------
    (ik, is_rotation) where:
    - ik           : the newly saved IdentityKey instance.
    - is_rotation  : True only when a prior identity key existed AND the new
                     Curve25519 key differs byte-for-byte from the prior one.
                     First publish (no prior row) -> False.
                     Idempotent re-publish of the same key -> False.
                     Actual device change / key regeneration -> True.
    """
    # Capture any existing Curve25519 key BEFORE the delete so we can
    # distinguish a genuine rotation from a first-time publish.
    prior = IdentityKey.objects.filter(user_id=user_id).values_list(
        "ik_pub_curve25519", flat=True
    ).first()

    # Wipe any existing key material for this user before registering new keys.
    IdentityKey.objects.filter(user_id=user_id).delete()
    SignedPreKey.objects.filter(user_id=user_id).delete()
    OneTimePreKey.objects.filter(user_id=user_id).delete()

    ik = IdentityKey.objects.create(
        user_id=user_id,
        ik_pub_curve25519=ik_curve,
        ik_pub_ed25519=ik_ed,
        rotated_at=timezone.now(),
    )
    SignedPreKey.objects.create(
        user_id=user_id,
        spk_id=1,
        spk_pub=spk_pub,
        spk_sig=spk_sig,
        is_active=True,
    )

    is_rotation = prior is not None and prior != ik_curve

    logger.info(
        "pm.identity_registered: user_id=%s is_rotation=%s ik_curve_len=%d ik_ed_len=%d",
        user_id,
        is_rotation,
        len(ik_curve),
        len(ik_ed),
    )

    if not is_rotation:
        transaction.on_commit(lambda: _notify_friends_peer_registered(user_id))

    return ik, is_rotation


def _notify_friends_peer_registered(user_id: int) -> None:
    """Fan out `pm_peer_registered` to each friend's channel group.

    Called only on first-publish (is_rotation=False). Rotations already
    trigger `pm_key_rotate_alarm` via the consumer, which is a stronger
    signal (it forces session replacement, not just retry). This push
    lets senders who are currently in the 10-60s retry-backoff window
    cancel the timer and retry immediately once the peer's keys exist.
    Idempotent: if the friend has no open WS, the channel layer drops
    the event silently.
    """
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    from FRIEND.models import Friend

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    peer_ids = list(
        Friend.objects.filter(from_user_id=user_id).values_list("to_user_id", flat=True)
    )
    for peer_id in peer_ids:
        try:
            async_to_sync(channel_layer.group_send)(
                f"pm_user_{peer_id}",
                {"type": "pm_peer_registered", "payload": {"peer_id": user_id}},
            )
        except Exception as exc:
            logger.warning(
                "pm.peer_registered_fanout_failed: user_id=%s peer_id=%s err=%s",
                user_id,
                peer_id,
                exc,
            )


# ---------------------------------------------------------------------------
# OTPK pool management
# ---------------------------------------------------------------------------


@transaction.atomic
def consume_one_time_prekey(user_id: int) -> Optional[dict]:
    """
    Atomically select and delete one OTPK from the pool.

    Uses SELECT FOR UPDATE to serialise concurrent fetches (e.g. two devices
    initiating a session with the same user simultaneously). If the pool is
    empty, returns None — the caller should fall back to SPK-only bundle.

    Returns
    -------
    {"otpk_id": str, "otpk_pub": str} or None
    """
    # SELECT FOR UPDATE on the first available OTPK for this user.
    qs = (
        OneTimePreKey.objects.select_for_update()
        .filter(user_id=user_id)
        .order_by("id")[:1]
    )
    otpk = qs.first()
    if otpk is None:
        logger.info("pm.otpk_pool_empty: user_id=%s", user_id)
        return None

    result = {"otpk_id": otpk.otpk_id, "otpk_pub": otpk.otpk_pub}
    otpk.delete()
    logger.info("pm.otpk_consumed: user_id=%s otpk_id=%r", user_id, otpk.otpk_id)
    return result


@transaction.atomic
def publish_one_time_prekeys(user_id: int, keys: list[dict]) -> int:
    """
    Bulk-insert a batch of OTPKs for a user.

    Each element of keys must be {"otpk_id": str, "otpk_pub": str}.
    Existing keys with the same otpk_id are skipped (ignore_conflicts=True).

    Returns the count of rows actually inserted.
    """
    # Cap the pool at 150 by rejecting publishes that would exceed it.
    current_count = OneTimePreKey.objects.filter(user_id=user_id).count()
    available_slots = max(0, 150 - current_count)
    keys_to_insert = keys[:available_slots]

    if not keys_to_insert:
        logger.info("pm.otpk_publish_skipped: user_id=%s pool_full=%s", user_id, current_count)
        return 0

    objs = [
        OneTimePreKey(
            user_id=user_id,
            otpk_id=k["otpk_id"],
            otpk_pub=k["otpk_pub"],
        )
        for k in keys_to_insert
    ]
    created = OneTimePreKey.objects.bulk_create(objs, ignore_conflicts=True)
    count = len(created)
    logger.info("pm.otpk_published: user_id=%s count=%d", user_id, count)
    return count


def get_otpk_pool_size(user_id: int) -> int:
    """Return the current number of OTPKs in the pool for this user."""
    return OneTimePreKey.objects.filter(user_id=user_id).count()


# ---------------------------------------------------------------------------
# Prekey bundle
# ---------------------------------------------------------------------------


@transaction.atomic
def prekey_bundle_for(user_id: int) -> Optional[dict]:
    """
    Assemble the prekey bundle for user_id.

    Decorated with @transaction.atomic so that the inner consume_one_time_prekey
    call (which has its own atomic decorator) runs as a SAVEPOINT within this
    outer transaction. If bundle assembly raises after the OTPK has been consumed
    (e.g. SPK lookup fails), the outer transaction rolls back — including the
    SAVEPOINT — and the OTPK is NOT permanently burned.

    Without this decorator, consume_one_time_prekey's own atomic block commits
    immediately, so any exception raised during subsequent assembly would burn
    an OTPK with no corresponding bundle delivered to the requester.

    Consumes one OTPK atomically (falls back to None if pool is empty).
    Returns None if the user has no registered identity key.

    The returned dict contains only public key material — no secrets.

    Returns
    -------
    {
        "user_id": int,
        "ik_pub_curve25519": str,
        "ik_pub_ed25519": str,
        "spk_id": int,
        "spk_pub": str,
        "spk_sig": str,
        "otpk_id": str | None,
        "otpk_pub": str | None,
    }
    or None if the user has no identity registered.
    """
    try:
        ik = IdentityKey.objects.get(user_id=user_id)
    except IdentityKey.DoesNotExist:
        logger.info("pm.bundle_not_found: user_id=%s no identity", user_id)
        return None

    try:
        spk = SignedPreKey.objects.get(user_id=user_id, is_active=True)
    except SignedPreKey.DoesNotExist:
        logger.warning("pm.bundle_no_active_spk: user_id=%s", user_id)
        return None

    otpk = consume_one_time_prekey(user_id)

    return {
        "user_id": user_id,
        "ik_pub_curve25519": ik.ik_pub_curve25519,
        "ik_pub_ed25519": ik.ik_pub_ed25519,
        "spk_id": spk.spk_id,
        "spk_pub": spk.spk_pub,
        "spk_sig": spk.spk_sig,
        "otpk_id": otpk["otpk_id"] if otpk else None,
        "otpk_pub": otpk["otpk_pub"] if otpk else None,
    }


# ---------------------------------------------------------------------------
# Envelope store / fetch / delete
# ---------------------------------------------------------------------------


@transaction.atomic
def store_envelope(
    sender_id: int,
    recipient_id: int,
    ciphertext_b64: str,
    message_type: int,
    otpk_id_used: Optional[str] = None,
) -> EncryptedEnvelope:
    """
    Persist an encrypted envelope for offline delivery.

    Parameters
    ----------
    sender_id     : pk of the sending ChatUser
    recipient_id  : pk of the receiving ChatUser
    ciphertext_b64: Olm ciphertext, base64-encoded (max 65536 chars)
    message_type  : 0 = PreKey, 1 = regular
    otpk_id_used  : the OTPK consumed during X3DH (None for regular messages)

    Returns the saved EncryptedEnvelope instance.
    """
    expires_at = timezone.now() + timedelta(days=_ENVELOPE_TTL_DAYS)
    envelope = EncryptedEnvelope.objects.create(
        sender_id=sender_id,
        recipient_id=recipient_id,
        ciphertext_b64=ciphertext_b64,
        message_type=message_type,
        otpk_id_used=otpk_id_used,
        expires_at=expires_at,
    )
    logger.info(
        "pm.envelope_stored: envelope_id=%s sender_id=%s recipient_id=%s "
        "message_type=%d ciphertext_len=%d",
        envelope.pk,
        sender_id,
        recipient_id,
        message_type,
        len(ciphertext_b64),
    )
    return envelope


_ENVELOPE_FETCH_CHUNK = 100   # rows streamed per iterator step
_ENVELOPE_DELETE_BATCH = 500  # max IDs per DELETE IN (…)


@transaction.atomic
def fetch_and_delete_envelopes_for(user_id: int) -> list[dict]:
    """
    Atomically fetch and delete all pending envelopes for a recipient.

    The SELECT and DELETE happen within the same transaction so envelopes
    are never lost between fetch and delete (crash-before-ACK is handled
    by the WS consumer's reconnect re-delivery, not here).

    Memory-safe implementation — uses .iterator(chunk_size=100) instead of
    list() so that a recipient with a large backlog (e.g. thousands of
    envelopes) does not materialise the entire queryset into Python memory and
    risk OOMing the ASGI worker.

    Ordering is preserved: .order_by("created_at") is applied before the
    iterator, so envelopes are yielded oldest-first. Within each 100-row
    chunk and across chunks the Olm ratchet receives messages in the correct
    sequence. (Olm handles occasional out-of-order delivery by design, so
    this is belt-and-suspenders.)

    Trade-off: chunking means the delete is not strictly "all-or-nothing" —
    if the worker crashes mid-iteration some chunks will already be deleted
    while later ones remain. This is the same trade-off as before (the prior
    implementation also deleted all rows in one shot after full materialisation,
    so a mid-delivery crash left envelopes undelivered). Delete-on-ack for the
    offline path is a separate product decision tracked in the plan deferrals.

    Returns a list of dicts suitable for JSON serialisation:
    [{"envelope_id": str, "sender_id": int, "ciphertext_b64": str,
      "message_type": int, "otpk_id_used": str|None, "created_at": str}, ...]
    """
    qs = (
        EncryptedEnvelope.objects.filter(recipient_id=user_id)
        .select_for_update()
        .order_by("created_at")
    )

    results: list[dict] = []
    id_batch: list = []

    for e in qs.iterator(chunk_size=_ENVELOPE_FETCH_CHUNK):
        results.append(
            {
                "envelope_id": str(e.pk),
                "sender_id": e.sender_id,
                "ciphertext_b64": e.ciphertext_b64,
                "message_type": e.message_type,
                "otpk_id_used": e.otpk_id_used,
                "created_at": e.created_at.isoformat(),
            }
        )
        id_batch.append(e.pk)
        if len(id_batch) >= _ENVELOPE_DELETE_BATCH:
            EncryptedEnvelope.objects.filter(pk__in=id_batch).delete()
            id_batch = []

    # Delete any remaining IDs that did not fill a full batch.
    if id_batch:
        EncryptedEnvelope.objects.filter(pk__in=id_batch).delete()

    if results:
        logger.info(
            "pm.envelopes_fetched_deleted: recipient_id=%s count=%d",
            user_id,
            len(results),
        )
    return results


@transaction.atomic
def delete_envelope_for_recipient(envelope_id: str, recipient_id: int) -> bool:
    """
    Delete a single envelope, enforcing that recipient_id matches.

    The recipient_id filter prevents spoofed ACKs from deleting envelopes
    belonging to other users. Returns True if a row was deleted, False if
    no matching row exists (already deleted or wrong recipient).
    """
    deleted_count, _ = EncryptedEnvelope.objects.filter(
        pk=envelope_id,
        recipient_id=recipient_id,
    ).delete()

    if deleted_count:
        logger.info(
            "pm.envelope_acked: envelope_id=%s recipient_id=%s",
            envelope_id,
            recipient_id,
        )
        return True

    logger.warning(
        "pm.envelope_ack_miss: envelope_id=%s recipient_id=%s "
        "(already deleted or wrong recipient)",
        envelope_id,
        recipient_id,
    )
    return False


# ---------------------------------------------------------------------------
# Session tracking
# ---------------------------------------------------------------------------


@transaction.atomic
def get_or_create_session(user_a_id: int, user_b_id: int) -> tuple[PrivateSession, bool]:
    """
    Get or create a PrivateSession for the pair (user_a_id, user_b_id).

    Enforces the canonical ordering (min < max) required by the DB CHECK
    constraint. Returns (session, created).
    """
    lo, hi = (user_a_id, user_b_id) if user_a_id < user_b_id else (user_b_id, user_a_id)
    return PrivateSession.objects.get_or_create(user_a_id=lo, user_b_id=hi)


# ---------------------------------------------------------------------------
# Session peer helpers
# ---------------------------------------------------------------------------


def active_session_peer_ids_for(user_id: int) -> list[int]:
    """
    Return the list of peer user IDs that share a PrivateSession with user_id.

    A "session" exists whenever two users have previously initiated X3DH key
    exchange — it does not require an active WebSocket connection. This is used
    by _handle_key_rotate to fan out pm_key_rotate_alarm to all peers who hold
    Olm session state derived from the now-rotated identity key.

    The rotating user themselves is excluded from the result (they should not
    receive their own alarm).

    Returns a deduplicated list; order is unspecified.
    """
    from django.db.models import Q

    peer_ids: set[int] = set()
    for row in PrivateSession.objects.filter(
        Q(user_a_id=user_id) | Q(user_b_id=user_id)
    ).values("user_a_id", "user_b_id"):
        peer = row["user_b_id"] if row["user_a_id"] == user_id else row["user_a_id"]
        peer_ids.add(peer)
    return list(peer_ids)


# ---------------------------------------------------------------------------
# Panic wipe helpers
# ---------------------------------------------------------------------------


@transaction.atomic
def wipe_all_pm_data_for(user_id: int) -> list[int]:
    """
    Atomically delete every pm_* row associated with user_id.

    Order of deletion respects FK constraints:
        envelopes (no FK to sessions) → sessions → OTPKs → SPK → IK

    Returns the list of peer user IDs (for WS pm.wipe broadcast) collected
    before deletion.
    """
    from django.db.models import Q

    peer_ids: list[int] = []
    for s in PrivateSession.objects.filter(
        Q(user_a_id=user_id) | Q(user_b_id=user_id)
    ).values("user_a_id", "user_b_id"):
        peer = s["user_b_id"] if s["user_a_id"] == user_id else s["user_a_id"]
        peer_ids.append(peer)

    # Delete sent and received envelopes.
    EncryptedEnvelope.objects.filter(
        Q(sender_id=user_id) | Q(recipient_id=user_id)
    ).delete()

    # Delete session records.
    PrivateSession.objects.filter(
        Q(user_a_id=user_id) | Q(user_b_id=user_id)
    ).delete()

    # Delete key material.
    OneTimePreKey.objects.filter(user_id=user_id).delete()
    SignedPreKey.objects.filter(user_id=user_id).delete()
    IdentityKey.objects.filter(user_id=user_id).delete()

    logger.info(
        "pm.panic_wipe: user_id=%s peers_notified=%d",
        user_id,
        len(peer_ids),
    )
    return peer_ids
