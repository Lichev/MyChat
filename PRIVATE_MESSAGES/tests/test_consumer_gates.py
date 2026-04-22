"""
test_consumer_gates.py

Verifies that PrivateMessageConsumer correctly gates the identity.fingerprint
event behind friendship check (C5 fix).
"""

from django.test import TransactionTestCase
from channels.testing import WebsocketCommunicator
from channels.routing import URLRouter
from django.contrib.auth import get_user_model
from django.urls import re_path

from PRIVATE_MESSAGES.consumers import PrivateMessageConsumer
from PRIVATE_MESSAGES.models import IdentityKey

UserModel = get_user_model()


def _make_user(username: str) -> UserModel:
    return UserModel.objects.create_user(username=username, password="testpass123!")


def _make_friends(user_a, user_b):
    from FRIEND.models import Friend
    Friend.objects.get_or_create(from_user=user_a, to_user=user_b)
    Friend.objects.get_or_create(from_user=user_b, to_user=user_a)


async def _get_communicator(user, peer_id: int) -> WebsocketCommunicator:
    app = URLRouter([
        re_path(r"^ws/pm/(?P<user_id>\d+)/$", PrivateMessageConsumer.as_asgi()),
    ])
    comm = WebsocketCommunicator(app, f"/ws/pm/{peer_id}/")
    comm.scope["user"] = user
    return comm


class ConnectFriendshipGateTest(TransactionTestCase):
    """H6: PrivateMessageConsumer.connect() must reject non-friends with code 4003."""

    def setUp(self):
        self.user_a = _make_user("connect_gate_a")
        self.user_b = _make_user("connect_gate_b")

    async def test_connect_rejects_non_friend_fast(self):
        """
        Opening a WebSocket to a non-friend peer must result in close code 4003
        without accepting the connection.
        """
        comm = await _get_communicator(self.user_a, self.user_b.pk)
        connected, subprotocol = await comm.connect()
        # With the connect-level gate, the consumer closes without accepting —
        # channels testing reports connected=False when the server rejects.
        if connected:
            # If connected=True was returned, the server must have sent a close.
            close_code = await comm.receive_output()
            self.assertEqual(
                close_code.get("code"), 4003,
                f"Expected close code 4003 for non-friend, got: {close_code}"
            )
        else:
            # Connection was refused outright — pass.
            pass

    async def test_connect_accepts_friend(self):
        """
        Opening a WebSocket to a friend must succeed (connected=True).
        """
        from asgiref.sync import sync_to_async
        await sync_to_async(_make_friends)(self.user_a, self.user_b)

        comm = await _get_communicator(self.user_a, self.user_b.pk)
        connected, _ = await comm.connect()
        self.assertTrue(connected, "Expected connection to succeed for a friend peer.")
        await comm.disconnect()


class IdentityFingerprintGateTest(TransactionTestCase):
    """C5: identity.fingerprint must be blocked for non-friends."""

    def setUp(self):
        self.user_a = _make_user("fp_gate_a")
        self.user_b = _make_user("fp_gate_b")

    async def _register_ik_for_b(self):
        from asgiref.sync import sync_to_async
        await sync_to_async(IdentityKey.objects.create)(
            user=self.user_b,
            ik_pub_curve25519="A" * 44,
            ik_pub_ed25519="B" * 44,
        )

    async def test_identity_fingerprint_blocks_non_friend(self):
        """A non-friend must receive type=error code=forbidden on identity.fingerprint."""
        await self._register_ik_for_b()

        comm = await _get_communicator(self.user_a, self.user_b.pk)
        connected, _ = await comm.connect()
        self.assertTrue(connected)

        try:
            await comm.send_json_to({"type": "identity.fingerprint"})
            response = await comm.receive_json_from()
            self.assertEqual(response.get("type"), "error",
                             f"Expected error response, got: {response}")
            self.assertEqual(response.get("code"), "forbidden",
                             f"Expected forbidden code, got: {response}")
        finally:
            await comm.disconnect()

    async def test_identity_fingerprint_succeeds_for_friend(self):
        """A friend must receive identity.fingerprint.response."""
        from asgiref.sync import sync_to_async
        await self._register_ik_for_b()
        await sync_to_async(_make_friends)(self.user_a, self.user_b)

        comm = await _get_communicator(self.user_a, self.user_b.pk)
        connected, _ = await comm.connect()
        self.assertTrue(connected)

        try:
            await comm.send_json_to({"type": "identity.fingerprint"})
            response = await comm.receive_json_from()
            self.assertEqual(response.get("type"), "identity.fingerprint.response",
                             f"Expected fingerprint response, got: {response}")
            self.assertEqual(response.get("peer_id"), self.user_b.pk)
        finally:
            await comm.disconnect()
