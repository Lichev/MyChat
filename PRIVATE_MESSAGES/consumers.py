"""
PrivateMessageConsumer — WebSocket dumb-pipe for end-to-end encrypted DMs.

Security model:
- Anonymous connections are rejected at handshake with code 4001.
- Friendship gate is enforced BEFORE any prekey read, envelope write, or
  session init. Non-friends receive an opaque error event with no DB touch.
- Rate limits are checked BEFORE any expensive operation.
- Sender identity comes exclusively from scope['user'] — client-supplied
  sender IDs are ignored.
- ACK handler filters WHERE recipient_id = self.scope['user'].id to block
  spoofed ACKs from deleting other users' envelopes.
- Ciphertext fields are NEVER logged.

Per-user channel group name: pm_user_<user_id>
WS path: ws/pm/<user_id>/  (user_id in URL is the *peer*, not self)
"""

import logging
import uuid

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model

from . import rate_limit as rl
from . import services

UserModel = get_user_model()
logger = logging.getLogger(__name__)

# Maximum ciphertext length (blueprint § "Wire events")
_MAX_CIPHERTEXT_LEN = 65536
# Maximum OTPK batch size per publish event (pool cap / 2 for safety)
_MAX_OTPK_BATCH = 100
# Maximum otpk_id / otpk_pub field length
_MAX_KEY_FIELD_LEN = 64
# Maximum spk_sig field length
_MAX_SPK_SIG_LEN = 128

# Valid message_type values for envelope.send
_VALID_MESSAGE_TYPES = frozenset({0, 1})


def _user_group(user_id: int) -> str:
    """Channel group name for a specific user."""
    return f"pm_user_{user_id}"


class PrivateMessageConsumer(AsyncJsonWebsocketConsumer):
    """
    Handles all private-message WebSocket events.

    The URL kwarg ``user_id`` is the PEER the client wants to message,
    not the authenticated user themselves. We join the authenticated user's
    own group so that any peer can push events to us via group_send.
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        user = self.scope.get("user")

        if not user or not user.is_authenticated:
            # Reject anonymous connections immediately — do not accept.
            await self.close(code=4001)
            return

        self.user = user
        self.user_id: int = user.id
        self.my_group: str = _user_group(self.user_id)

        # URL kwarg is validated: must be a positive integer.
        raw_peer_id = self.scope["url_route"]["kwargs"].get("user_id", "")
        try:
            self.peer_id = int(raw_peer_id)
            if self.peer_id <= 0:
                raise ValueError("peer_id must be positive")
        except (ValueError, TypeError):
            logger.warning(
                "pm.connect_rejected: user_id=%s invalid peer_id=%r",
                self.user_id,
                raw_peer_id,
            )
            await self.close(code=4002)
            return

        if self.peer_id == self.user_id:
            logger.warning(
                "pm.connect_rejected: user_id=%s self-connection attempt",
                self.user_id,
            )
            await self.close(code=4002)
            return

        # H6 fix: connect-level friendship gate — reject non-friends before
        # accepting the WebSocket to avoid wasting a channel-layer slot.
        # Per-handler friendship gates (in _assert_friends) are kept as
        # defence-in-depth; this is an early fast-path rejection only.
        if not await self._check_friendship():
            logger.info(
                "pm.connect_rejected: user_id=%s peer_id=%s not_friends",
                self.user_id,
                self.peer_id,
            )
            await self.close(code=4003)
            return

        # Join the authenticated user's own channel group so peers can push.
        await self.channel_layer.group_add(self.my_group, self.channel_name)
        await self.accept()

        logger.info(
            "pm.connected: user_id=%s peer_id=%s channel=%s",
            self.user_id,
            self.peer_id,
            self.channel_name,
        )

        # Deliver any pending envelopes immediately on connect.
        await self._deliver_pending_envelopes()

    async def disconnect(self, code):
        if hasattr(self, "my_group"):
            await self.channel_layer.group_discard(self.my_group, self.channel_name)
            logger.info(
                "pm.disconnected: user_id=%s code=%s",
                self.user_id,
                code,
            )

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    async def receive_json(self, content, **kwargs):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4001)
            return

        if not isinstance(content, dict):
            await self._send_error("invalid_payload", "Expected a JSON object.")
            return

        event_type = content.get("type")
        if not isinstance(event_type, str):
            await self._send_error("invalid_payload", "Missing or non-string 'type' field.")
            return

        handler = {
            "session.init":           self._handle_session_init,
            "prekey.request":         self._handle_prekey_request,
            "prekey.publish":         self._handle_prekey_publish,
            "envelope.send":          self._handle_envelope_send,
            "envelope.ack":           self._handle_envelope_ack,
            "identity.fingerprint":   self._handle_identity_fingerprint,
            "key.rotate":             self._handle_key_rotate,
            "key.replenish":          self._handle_key_replenish,
        }.get(event_type)

        if handler is None:
            await self._send_error("unknown_event", "Unrecognised event type.")
            return

        await handler(content)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _handle_session_init(self, content: dict):
        """Client signals intent to open a session with the peer."""
        ok, remaining, retry_after = rl.check("session.init", self.user_id)
        if not ok:
            await self._send_rate_limit_error(retry_after)
            return

        if not await self._assert_friends():
            return

        session, created = await sync_to_async(services.get_or_create_session)(
            self.user_id, self.peer_id
        )
        await self.send_json({
            "type": "session.init.ack",
            "session_id": session.pk,
            "created": created,
        })

    async def _handle_prekey_request(self, content: dict):
        """Client requests the prekey bundle for the peer (to initiate X3DH)."""
        ok, remaining, retry_after = rl.check("prekey.request", self.user_id)
        if not ok:
            await self._send_rate_limit_error(retry_after)
            return

        if not await self._assert_friends():
            return

        bundle = await sync_to_async(services.prekey_bundle_for)(self.peer_id)
        if bundle is None:
            await self._send_error("prekey_not_found", "Peer has no registered identity.")
            return

        pool_size = await sync_to_async(services.get_otpk_pool_size)(self.peer_id)

        # Signal the peer to replenish OTPKs if pool is below threshold.
        if pool_size < 20:
            await self.channel_layer.group_send(
                _user_group(self.peer_id),
                {
                    "type": "pm_key_rotate_alarm",
                    "payload": {"remaining_otpks": pool_size},
                },
            )

        await self.send_json({
            "type": "prekey.bundle",
            "bundle": bundle,
        })

    async def _handle_prekey_publish(self, content: dict):
        """Client publishes a batch of new OTPKs to the server pool."""
        ok, remaining, retry_after = rl.check("prekey.publish", self.user_id)
        if not ok:
            await self._send_rate_limit_error(retry_after)
            return

        keys = content.get("keys")
        if not isinstance(keys, list) or not keys:
            await self._send_error("invalid_payload", "'keys' must be a non-empty list.")
            return

        if len(keys) > _MAX_OTPK_BATCH:
            await self._send_error(
                "invalid_payload",
                f"'keys' list exceeds max batch size of {_MAX_OTPK_BATCH}.",
            )
            return

        validated: list[dict] = []
        for entry in keys:
            if not isinstance(entry, dict):
                await self._send_error("invalid_payload", "Each key entry must be an object.")
                return
            otpk_id = entry.get("otpk_id")
            otpk_pub = entry.get("otpk_pub")
            if (
                not isinstance(otpk_id, str)
                or not isinstance(otpk_pub, str)
                or len(otpk_id) > _MAX_KEY_FIELD_LEN
                or len(otpk_pub) > _MAX_KEY_FIELD_LEN
                or not otpk_id
                or not otpk_pub
            ):
                await self._send_error("invalid_payload", "Invalid key entry fields.")
                return
            validated.append({"otpk_id": otpk_id, "otpk_pub": otpk_pub})

        count = await sync_to_async(services.publish_one_time_prekeys)(
            self.user_id, validated
        )
        await self.send_json({"type": "prekey.publish.ack", "inserted": count})

    async def _handle_envelope_send(self, content: dict):
        """
        Client sends an encrypted envelope to the peer.

        Friendship gate → rate limit → validate fields → store → forward.
        """
        # Friendship gate first — no rate-limit burn on non-friends.
        if not await self._assert_friends():
            return

        ok, remaining, retry_after = rl.check("envelope.send", self.user_id)
        if not ok:
            await self._send_rate_limit_error(retry_after)
            return

        # Validate all fields before touching ORM.
        ciphertext_b64 = content.get("ciphertext_b64")
        message_type = content.get("message_type")
        otpk_id_used = content.get("otpk_id_used")

        if not isinstance(ciphertext_b64, str) or not ciphertext_b64:
            await self._send_error("invalid_payload", "Missing or empty 'ciphertext_b64'.")
            return
        if len(ciphertext_b64) > _MAX_CIPHERTEXT_LEN:
            await self._send_error(
                "invalid_payload",
                f"'ciphertext_b64' exceeds max length of {_MAX_CIPHERTEXT_LEN}.",
            )
            return
        if message_type not in _VALID_MESSAGE_TYPES:
            await self._send_error("invalid_payload", "'message_type' must be 0 or 1.")
            return
        if otpk_id_used is not None and (
            not isinstance(otpk_id_used, str)
            or len(otpk_id_used) > _MAX_KEY_FIELD_LEN
        ):
            await self._send_error("invalid_payload", "Invalid 'otpk_id_used'.")
            return

        envelope = await sync_to_async(services.store_envelope)(
            sender_id=self.user_id,
            recipient_id=self.peer_id,
            ciphertext_b64=ciphertext_b64,
            message_type=message_type,
            otpk_id_used=otpk_id_used,
        )

        # ACK the sender.
        await self.send_json({
            "type": "envelope.send.ack",
            "envelope_id": str(envelope.pk),
        })

        # Forward to peer's channel group for real-time delivery.
        await self.channel_layer.group_send(
            _user_group(self.peer_id),
            {
                "type": "pm_envelope_deliver",
                "envelope_id": str(envelope.pk),
                "sender_id": self.user_id,
                "ciphertext_b64": ciphertext_b64,
                "message_type": message_type,
                "otpk_id_used": otpk_id_used,
            },
        )

    async def _handle_envelope_ack(self, content: dict):
        """
        Recipient acknowledges successful (or failed) decryption.
        Server deletes the envelope regardless of decrypt_error flag.
        ACK filter enforces recipient_id = authenticated user — blocks spoofed ACKs.
        """
        envelope_id_raw = content.get("envelope_id")
        if not isinstance(envelope_id_raw, str):
            await self._send_error("invalid_payload", "Missing or non-string 'envelope_id'.")
            return

        # Validate UUID format before DB call.
        try:
            envelope_uuid = str(uuid.UUID(envelope_id_raw))
        except ValueError:
            await self._send_error("invalid_payload", "Invalid 'envelope_id' format.")
            return

        decrypt_error: bool = bool(content.get("decrypt_error", False))

        # Delete inside a transaction — failure here raises and the WS frame
        # is not acked, triggering a retry from the client.
        deleted = await sync_to_async(services.delete_envelope_for_recipient)(
            envelope_id=envelope_uuid,
            recipient_id=self.user_id,  # ← enforced server-side; never from client
        )

        if not deleted:
            # Already deleted (duplicate ACK) — silently succeed so client
            # doesn't retry forever.
            logger.info(
                "pm.envelope_ack_duplicate: envelope_id=%s user_id=%s",
                envelope_uuid,
                self.user_id,
            )

        await self.send_json({
            "type": "envelope.ack.confirm",
            "envelope_id": envelope_uuid,
            "deleted": deleted,
            "decrypt_error": decrypt_error,
        })

    async def _handle_identity_fingerprint(self, content: dict):
        """Client requests the peer's public identity key for safety-number derivation."""
        # C5 fix: only friends may exchange identity key material.
        if not await self._assert_friends():
            return

        ok, remaining, retry_after = rl.check("identity.fingerprint", self.user_id)
        if not ok:
            await self._send_rate_limit_error(retry_after)
            return

        from .models import IdentityKey

        try:
            ik = await sync_to_async(IdentityKey.objects.get)(user_id=self.peer_id)
        except IdentityKey.DoesNotExist:
            await self._send_error("not_found", "Peer has no registered identity key.")
            return

        await self.send_json({
            "type": "identity.fingerprint.response",
            "peer_id": self.peer_id,
            "ik_pub_curve25519": ik.ik_pub_curve25519,
            "ik_pub_ed25519": ik.ik_pub_ed25519,
        })

    async def _handle_key_rotate(self, content: dict):
        """
        Client triggers emergency IK rotation.
        Validates and re-registers identity + SPK; flushes OTPK pool.
        """
        ok, remaining, retry_after = rl.check("key.rotate", self.user_id)
        if not ok:
            await self._send_rate_limit_error(retry_after)
            return

        ik_curve = content.get("ik_pub_curve25519")
        ik_ed = content.get("ik_pub_ed25519")
        spk_pub = content.get("spk_pub")
        spk_sig = content.get("spk_sig")

        if not all(isinstance(v, str) and v for v in [ik_curve, ik_ed, spk_pub, spk_sig]):
            await self._send_error("invalid_payload", "Missing key material for rotation.")
            return
        if len(ik_curve) > _MAX_KEY_FIELD_LEN or len(ik_ed) > _MAX_KEY_FIELD_LEN:
            await self._send_error("invalid_payload", "Key field too long.")
            return
        if len(spk_pub) > _MAX_KEY_FIELD_LEN or len(spk_sig) > _MAX_SPK_SIG_LEN:
            await self._send_error("invalid_payload", "SPK field too long.")
            return

        _, is_rotation = await sync_to_async(services.register_identity)(
            user_id=self.user_id,
            ik_curve=ik_curve,
            ik_ed=ik_ed,
            spk_pub=spk_pub,
            spk_sig=spk_sig,
        )

        # Only broadcast the key-change alarm on a GENUINE rotation — i.e., when a
        # prior identity key existed AND the new key differs from it. First publishes
        # and idempotent re-publishes of the same key produce no alarm.
        #
        # H1 fix: fan out to ALL peers that hold PrivateSession state with this user,
        # not just the single peer this socket happens to be connected to. Peers who
        # are not currently connected will receive the alarm when they reconnect via
        # the channel-layer group (they must re-join their own group on connect).
        #
        # Amplification concern: a rotating user could trigger N channel-layer group
        # sends. The existing key.rotate rate limit (1 per 6 hours) bounds this to
        # one fan-out per user per 6-hour window regardless of peer count — not an
        # exploitable amplification vector. Cybersec sign-off obtained before commit
        # (see orchestrator escalation note in plan-curried-otter.md H1).
        if is_rotation:
            peer_ids = await sync_to_async(services.active_session_peer_ids_for)(
                self.user_id
            )
            alarm_payload = {
                "type": "pm_key_rotate_alarm",
                "payload": {
                    "user_id": self.user_id,
                    "reason": "key_rotation",
                },
            }
            for peer_id in peer_ids:
                # Exclude the rotating user themselves (active_session_peer_ids_for
                # already excludes self, but be explicit as defence-in-depth).
                if peer_id != self.user_id:
                    await self.channel_layer.group_send(
                        _user_group(peer_id),
                        alarm_payload,
                    )

        await self.send_json({"type": "key.rotate.ack"})

    async def _handle_key_replenish(self, content: dict):
        """
        Convenience alias — client replenishes OTPKs in response to a
        pm.key_rotate_alarm low-pool notification.
        Delegates to prekey.publish handler.
        """
        await self._handle_prekey_publish(content)

    # ------------------------------------------------------------------
    # Group message handlers (pushed by other consumers via channel layer)
    # ------------------------------------------------------------------

    async def pm_envelope_deliver(self, event: dict):
        """Relay an envelope pushed by the sender's consumer to this recipient."""
        await self.send_json({
            "type": "envelope.deliver",
            "envelope_id": event["envelope_id"],
            "sender_id": event["sender_id"],
            "ciphertext_b64": event["ciphertext_b64"],
            "message_type": event["message_type"],
            "otpk_id_used": event.get("otpk_id_used"),
        })

    async def pm_key_rotate_alarm(self, event: dict):
        """Notify client that a peer's keys changed or OTPK pool is low."""
        await self.send_json({
            "type": "pm.key_rotate_alarm",
            "payload": event.get("payload", {}),
        })

    async def pm_peer_registered(self, event: dict):
        """Peer just bootstrapped — client can retry X3DH immediately."""
        await self.send_json({
            "type": "peer.registered",
            "payload": event.get("payload", {}),
        })

    async def pm_wipe(self, event: dict):
        """Notify client that a peer has performed a panic-wipe."""
        await self.send_json({
            "type": "pm.wipe",
            "peer_id": event.get("peer_id"),
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _deliver_pending_envelopes(self):
        """
        Fetch and deliver any offline-stored envelopes on connect.
        Each delivered envelope is already deleted inside the same txn
        by fetch_and_delete_envelopes_for — the client must ACK to confirm
        decryption; if it crashes before ACK the envelope is already gone
        (delete-on-fetch, not delete-on-ack for the offline case per blueprint).
        """
        envelopes = await sync_to_async(services.fetch_and_delete_envelopes_for)(
            self.user_id
        )
        for env in envelopes:
            await self.send_json({
                "type": "envelope.deliver",
                "envelope_id": env["envelope_id"],
                "sender_id": env["sender_id"],
                "ciphertext_b64": env["ciphertext_b64"],
                "message_type": env["message_type"],
                "otpk_id_used": env["otpk_id_used"],
            })

    @sync_to_async
    def _check_friendship(self) -> bool:
        """Return True if authenticated user and peer are friends."""
        from FRIEND.models import Friend

        try:
            peer = UserModel.objects.get(pk=self.peer_id)
        except UserModel.DoesNotExist:
            return False
        return Friend.objects.are_friends(self.user, peer)

    async def _assert_friends(self) -> bool:
        """
        Check friendship gate; send opaque error and return False if not friends.
        No DB reads happen before this check on guarded events.
        """
        if not await self._check_friendship():
            logger.info(
                "pm.friendship_gate_rejected: user_id=%s peer_id=%s",
                self.user_id,
                self.peer_id,
            )
            await self._send_error(
                "forbidden",
                "You must be friends to exchange private messages.",
            )
            return False
        return True

    async def _send_error(self, code: str, detail: str):
        """Send a structured error event to the client."""
        await self.send_json({"type": "error", "code": code, "detail": detail})

    async def _send_rate_limit_error(self, retry_after: int):
        """Send a rate-limit error — does not log user content."""
        await self.send_json({
            "type": "error",
            "code": "rate_limited",
            "detail": "Too many requests. Please slow down.",
            "retry_after": retry_after,
        })
