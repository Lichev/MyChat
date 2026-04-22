"""
test_replay.py

Covers ACK replay protection (server-level), spoofed-recipient ACK
rejection, and documents the server's intentional behaviour on
envelope.send replay (dumb-pipe by design; Olm ratchet is the primary
anti-replay defence for message ciphertext).
"""

import uuid

from django.test import TransactionTestCase
from django.utils import timezone
from datetime import timedelta
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.urls import re_path
from channels.routing import URLRouter

from PRIVATE_MESSAGES.consumers import PrivateMessageConsumer
from PRIVATE_MESSAGES.models import EncryptedEnvelope, IdentityKey, SignedPreKey
from PRIVATE_MESSAGES import services

UserModel = get_user_model()


def _make_user(username: str):
    return UserModel.objects.create_user(username=username, password="testpass123!")


def _make_friends(user_a, user_b):
    from FRIEND.models import Friend
    Friend.objects.get_or_create(from_user=user_a, to_user=user_b)
    Friend.objects.get_or_create(from_user=user_b, to_user=user_a)


def _make_identity(user):
    IdentityKey.objects.get_or_create(
        user=user,
        defaults={"ik_pub_curve25519": "A" * 44, "ik_pub_ed25519": "A" * 44},
    )
    SignedPreKey.objects.get_or_create(
        user=user,
        spk_id=1,
        defaults={"spk_pub": "A" * 44, "spk_sig": "B" * 88, "is_active": True},
    )


async def _communicator(user, peer_id: int) -> WebsocketCommunicator:
    app = URLRouter([
        re_path(r"^ws/pm/(?P<user_id>\d+)/$", PrivateMessageConsumer.as_asgi()),
    ])
    comm = WebsocketCommunicator(app, f"/ws/pm/{peer_id}/")
    comm.scope["user"] = user
    return comm


class EnvelopeAckReplayTest(TransactionTestCase):
    """
    A user replays an envelope.ack after the envelope has already been deleted.
    The server must return envelope.ack.confirm with deleted=False (idempotent
    no-op) — no crash, no error, no cross-user leakage.
    """

    def setUp(self):
        self.user_a = _make_user("replay_a")
        self.user_b = _make_user("replay_b")
        _make_friends(self.user_a, self.user_b)
        _make_identity(self.user_a)
        _make_identity(self.user_b)

    async def test_ack_replay_is_noop(self):
        # Store an envelope A→B
        envelope = await services.sync_to_async_store_envelope(
            self.user_a, self.user_b, "REPLAY_CIPHERTEXT", 1
        ) if hasattr(services, "sync_to_async_store_envelope") else None

        # Direct service call (sync) — store an envelope
        from asgiref.sync import sync_to_async
        store = sync_to_async(services.store_envelope)
        envelope = await store(
            sender_id=self.user_a.pk,
            recipient_id=self.user_b.pk,
            ciphertext_b64="REPLAY_CIPHERTEXT_001",
            message_type=1,
        )
        envelope_id = str(envelope.pk)

        # First ACK from B — should delete the row
        delete = sync_to_async(services.delete_envelope_for_recipient)
        deleted_first = await delete(envelope_id=envelope_id, recipient_id=self.user_b.pk)
        self.assertTrue(deleted_first, "First ACK should delete the envelope")

        # Verify row is gone
        exists = await EncryptedEnvelope.objects.filter(pk=envelope.pk).aexists()
        self.assertFalse(exists, "Envelope should be deleted after first ACK")

        # Replay ACK — should return False (idempotent no-op)
        deleted_second = await delete(envelope_id=envelope_id, recipient_id=self.user_b.pk)
        self.assertFalse(deleted_second, "Replay ACK must return False (idempotent)")

        # Still zero envelopes in the table
        count = await EncryptedEnvelope.objects.acount()
        self.assertEqual(count, 0)

    async def test_ack_replay_via_websocket_returns_confirm_not_error(self):
        """
        When a WS client replays an envelope.ack for an already-deleted
        envelope, the server must reply with envelope.ack.confirm (deleted=False)
        rather than an error, so the client doesn't retry forever.
        """
        from asgiref.sync import sync_to_async
        store = sync_to_async(services.store_envelope)
        envelope = await store(
            sender_id=self.user_a.pk,
            recipient_id=self.user_b.pk,
            ciphertext_b64="REPLAY_CIPHERTEXT_002",
            message_type=1,
        )
        envelope_id = str(envelope.pk)

        # Delete the envelope directly (simulate prior ACK)
        delete = sync_to_async(services.delete_envelope_for_recipient)
        await delete(envelope_id=envelope_id, recipient_id=self.user_b.pk)

        # Now B connects and sends a duplicate ACK via WS
        comm = await _communicator(self.user_b, self.user_a.pk)
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        try:
            await comm.send_json_to({"type": "envelope.ack", "envelope_id": envelope_id})
            response = await comm.receive_json_from()
            self.assertEqual(response.get("type"), "envelope.ack.confirm",
                             f"Expected envelope.ack.confirm, got: {response}")
            self.assertFalse(response.get("deleted"), "deleted should be False for replay")
        finally:
            await comm.disconnect()


class SpoofedRecipientAckTest(TransactionTestCase):
    """
    B cannot ACK an envelope that belongs to user C.
    delete_envelope_for_recipient filters on recipient_id; C's envelope is untouched.
    """

    def setUp(self):
        self.user_a = _make_user("spoof_a")
        self.user_b = _make_user("spoof_b")
        self.user_c = _make_user("spoof_c")
        _make_friends(self.user_a, self.user_c)
        _make_identity(self.user_a)
        _make_identity(self.user_c)

    async def test_spoofed_ack_does_not_delete_other_users_envelope(self):
        from asgiref.sync import sync_to_async
        store = sync_to_async(services.store_envelope)
        # A sends envelope to C (not B)
        envelope = await store(
            sender_id=self.user_a.pk,
            recipient_id=self.user_c.pk,
            ciphertext_b64="C_PRIVATE_CIPHERTEXT",
            message_type=1,
        )
        envelope_id = str(envelope.pk)

        # B tries to ACK C's envelope (cross-user spoof)
        delete = sync_to_async(services.delete_envelope_for_recipient)
        deleted = await delete(envelope_id=envelope_id, recipient_id=self.user_b.pk)
        self.assertFalse(deleted,
                         "B should not be able to ACK an envelope addressed to C")

        # C's envelope must still exist
        still_exists = await EncryptedEnvelope.objects.filter(pk=envelope.pk).aexists()
        self.assertTrue(still_exists, "C's envelope should remain untouched after spoof attempt")


class EnvelopeSendReplayDocumentationTest(TransactionTestCase):
    """
    Documents the server's intentional behaviour on envelope.send replay:
    the server is a dumb pipe and accepts repeated sends of the same ciphertext
    (it cannot distinguish replays at the byte level). The Olm ratchet on the
    recipient's device is the primary anti-replay defence (BAD_MESSAGE_MAC on
    second decrypt). This test confirms and documents that server-side
    behaviour rather than testing the Olm layer.
    """

    def setUp(self):
        self.user_a = _make_user("sendreplay_a")
        self.user_b = _make_user("sendreplay_b")
        _make_friends(self.user_a, self.user_b)
        _make_identity(self.user_a)
        _make_identity(self.user_b)

    async def test_server_accepts_duplicate_ciphertext(self):
        """
        Server must accept a second envelope.send with identical ciphertext
        (dumb-pipe design). Protection is Olm-side (BAD_MESSAGE_MAC).
        Two rows will exist; the test documents this.
        """
        _ciphertext = "IDENTICAL_CIPHERTEXT_REPLAY_TEST"
        from asgiref.sync import sync_to_async
        store = sync_to_async(services.store_envelope)
        e1 = await store(
            sender_id=self.user_a.pk,
            recipient_id=self.user_b.pk,
            ciphertext_b64=_ciphertext,
            message_type=1,
        )
        e2 = await store(
            sender_id=self.user_a.pk,
            recipient_id=self.user_b.pk,
            ciphertext_b64=_ciphertext,
            message_type=1,
        )
        count = await EncryptedEnvelope.objects.filter(
            sender=self.user_a, recipient=self.user_b
        ).acount()
        # By design: server stores both; Olm ratchet rejects the replay on client.
        # If this assertion fails, the server has added server-side anti-replay
        # (a good thing) — update accordingly.
        self.assertEqual(count, 2,
                         "Server (dumb pipe) stores duplicate ciphertext envelopes. "
                         "Olm ratchet is the primary anti-replay defence on the client side.")
