"""
test_friendship_gate.py

Verifies that the friendship gate in PrivateMessageConsumer is enforced
for session.init, envelope.send, and prekey.request. Uses
channels.testing.WebsocketCommunicator with InMemoryChannelLayer.
"""

from django.test import TransactionTestCase
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model

from PRIVATE_MESSAGES.models import PrivateSession, EncryptedEnvelope, OneTimePreKey
from PRIVATE_MESSAGES.consumers import PrivateMessageConsumer

UserModel = get_user_model()


def _make_user(username: str, password: str = "testpass123!"):
    return UserModel.objects.create_user(username=username, password=password)


def _make_friends(user_a, user_b):
    from FRIEND.models import Friend
    Friend.objects.get_or_create(from_user=user_a, to_user=user_b)
    Friend.objects.get_or_create(from_user=user_b, to_user=user_a)


async def _async_make_friends(user_a, user_b):
    from asgiref.sync import sync_to_async
    await sync_to_async(_make_friends)(user_a, user_b)


async def _get_communicator(user, peer_id: int) -> WebsocketCommunicator:
    """Build an authenticated WebsocketCommunicator for ws/pm/<peer_id>/."""
    from channels.routing import URLRouter
    from django.urls import re_path
    app = URLRouter([
        re_path(r"^ws/pm/(?P<user_id>\d+)/$", PrivateMessageConsumer.as_asgi()),
    ])
    comm = WebsocketCommunicator(app, f"/ws/pm/{peer_id}/")
    comm.scope["user"] = user
    return comm


class FriendshipGateTest(TransactionTestCase):
    """
    Non-friend users must receive type=error code=forbidden for any of
    session.init, envelope.send, and prekey.request. No DB row must be
    created in each case. Positive case: friends can perform all three ops.
    """

    def setUp(self):
        self.user_a = _make_user("gate_a")
        self.user_b = _make_user("gate_b")

    async def _connect_a_to_b(self):
        comm = await _get_communicator(self.user_a, self.user_b.pk)
        connected, _ = await comm.connect()
        self.assertTrue(connected, "WebSocket connection should be accepted for auth user")
        return comm

    # ── Negative cases (not friends) ─────────────────────────────────────

    async def test_session_init_blocked_when_not_friends(self):
        comm = await self._connect_a_to_b()
        try:
            await comm.send_json_to({"type": "session.init"})
            response = await comm.receive_json_from()
            self.assertEqual(response.get("type"), "error")
            self.assertEqual(response.get("code"), "forbidden")
            # No PrivateSession row should exist
            count = await PrivateSession.objects.acount()
            self.assertEqual(count, 0, "No PrivateSession should be created for non-friends")
        finally:
            await comm.disconnect()

    async def test_envelope_send_blocked_when_not_friends(self):
        comm = await self._connect_a_to_b()
        try:
            await comm.send_json_to({
                "type":          "envelope.send",
                "ciphertext_b64": "FAKECIPHERTEXT",
                "message_type":  1,
            })
            response = await comm.receive_json_from()
            self.assertEqual(response.get("type"), "error")
            self.assertEqual(response.get("code"), "forbidden")
            # No EncryptedEnvelope row should exist
            count = await EncryptedEnvelope.objects.acount()
            self.assertEqual(count, 0, "No EncryptedEnvelope should be created for non-friends")
        finally:
            await comm.disconnect()

    async def test_prekey_request_blocked_when_not_friends(self):
        # Pre-register an identity for B so the prekey_bundle_for won't fail
        # before the friendship gate — the gate must fire first.
        from PRIVATE_MESSAGES.models import IdentityKey, SignedPreKey
        await IdentityKey.objects.acreate(
            user=self.user_b,
            ik_pub_curve25519="A" * 44,
            ik_pub_ed25519="A" * 44,
        )
        await SignedPreKey.objects.acreate(
            user=self.user_b,
            spk_id=1,
            spk_pub="A" * 44,
            spk_sig="B" * 88,
            is_active=True,
        )
        # Publish some OTPKs for B
        await OneTimePreKey.objects.acreate(
            user=self.user_b,
            otpk_id="otk001",
            otpk_pub="C" * 44,
        )
        otpk_count_before = await OneTimePreKey.objects.filter(user=self.user_b).acount()

        comm = await self._connect_a_to_b()
        try:
            await comm.send_json_to({"type": "prekey.request"})
            response = await comm.receive_json_from()
            self.assertEqual(response.get("type"), "error")
            self.assertEqual(response.get("code"), "forbidden")
            # OTPKs must not have been consumed
            otpk_count_after = await OneTimePreKey.objects.filter(user=self.user_b).acount()
            self.assertEqual(
                otpk_count_after,
                otpk_count_before,
                "No OTPK should be consumed when friendship gate fires",
            )
        finally:
            await comm.disconnect()

    # ── Positive cases (friends) ──────────────────────────────────────────

    async def test_session_init_succeeds_when_friends(self):
        await _async_make_friends(self.user_a, self.user_b)
        comm = await self._connect_a_to_b()
        try:
            await comm.send_json_to({"type": "session.init"})
            response = await comm.receive_json_from()
            self.assertEqual(
                response.get("type"), "session.init.ack",
                f"Expected session.init.ack but got: {response}",
            )
            count = await PrivateSession.objects.acount()
            self.assertGreater(count, 0, "PrivateSession should be created for friends")
        finally:
            await comm.disconnect()

    async def test_envelope_send_succeeds_when_friends(self):
        await _async_make_friends(self.user_a, self.user_b)
        comm = await self._connect_a_to_b()
        try:
            await comm.send_json_to({
                "type":          "envelope.send",
                "ciphertext_b64": "FRIENDLYCIPHERTEXT",
                "message_type":  1,
            })
            response = await comm.receive_json_from()
            self.assertEqual(
                response.get("type"), "envelope.send.ack",
                f"Expected envelope.send.ack but got: {response}",
            )
            count = await EncryptedEnvelope.objects.acount()
            self.assertGreater(count, 0, "Envelope should be stored for friends")
        finally:
            await comm.disconnect()

    async def test_prekey_request_succeeds_when_friends(self):
        await _async_make_friends(self.user_a, self.user_b)
        from PRIVATE_MESSAGES.models import IdentityKey, SignedPreKey
        await IdentityKey.objects.acreate(
            user=self.user_b,
            ik_pub_curve25519="A" * 44,
            ik_pub_ed25519="A" * 44,
        )
        await SignedPreKey.objects.acreate(
            user=self.user_b,
            spk_id=1,
            spk_pub="A" * 44,
            spk_sig="B" * 88,
            is_active=True,
        )
        comm = await self._connect_a_to_b()
        try:
            await comm.send_json_to({"type": "prekey.request"})
            response = await comm.receive_json_from()
            self.assertEqual(
                response.get("type"), "prekey.bundle",
                f"Expected prekey.bundle but got: {response}",
            )
        finally:
            await comm.disconnect()
