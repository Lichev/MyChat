"""
test_key_change_alarm.py

Verifies that after a key.rotate event, the peer receives a
pm.key_rotate_alarm event via their channel group with the rotation reason.

Also verifies that first-time publishes and idempotent re-publishes of the
same key do NOT send the alarm, preventing false-positive security banners.
"""

import asyncio

from django.test import TransactionTestCase
from django.contrib.auth import get_user_model
from channels.testing import WebsocketCommunicator
from channels.layers import get_channel_layer
from django.urls import re_path
from channels.routing import URLRouter

from PRIVATE_MESSAGES.consumers import PrivateMessageConsumer
from PRIVATE_MESSAGES.models import IdentityKey, SignedPreKey

UserModel = get_user_model()


def _make_user(username: str):
    return UserModel.objects.create_user(username=username, password="testpass123!")


def _make_friends(user_a, user_b):
    from FRIEND.models import Friend
    Friend.objects.get_or_create(from_user=user_a, to_user=user_b)
    Friend.objects.get_or_create(from_user=user_b, to_user=user_a)


def _register_identity(user):
    IdentityKey.objects.get_or_create(
        user=user,
        defaults={"ik_pub_curve25519": "A" * 44, "ik_pub_ed25519": "A" * 44},
    )
    SignedPreKey.objects.get_or_create(
        user=user,
        spk_id=1,
        defaults={"spk_pub": "A" * 44, "spk_sig": "B" * 88, "is_active": True},
    )


def _app():
    return URLRouter([
        re_path(r"^ws/pm/(?P<user_id>\d+)/$", PrivateMessageConsumer.as_asgi()),
    ])


class KeyChangeAlarmTest(TransactionTestCase):
    """
    A performs key.rotate; B's channel group receives pm.key_rotate_alarm
    with reason='key_rotation' and the rotating user's user_id.
    """

    def setUp(self):
        self.user_a = _make_user("alarm_a")
        self.user_b = _make_user("alarm_b")
        _make_friends(self.user_a, self.user_b)
        _register_identity(self.user_a)
        _register_identity(self.user_b)

    async def test_key_rotate_sends_alarm_to_peer_group(self):
        """
        After A sends key.rotate, B's channel group (pm_user_<B.pk>) must
        receive a pm_key_rotate_alarm event with payload.reason='key_rotation'.
        """
        channel_layer = get_channel_layer()
        peer_group = f"pm_user_{self.user_b.pk}"
        test_channel = "test_alarm_recv_ch"

        await channel_layer.group_add(peer_group, test_channel)

        # A connects and sends key.rotate
        comm_a = WebsocketCommunicator(_app(), f"/ws/pm/{self.user_b.pk}/")
        comm_a.scope["user"] = self.user_a
        connected, _ = await comm_a.connect()
        self.assertTrue(connected)

        try:
            await comm_a.send_json_to({
                "type":             "key.rotate",
                "ik_pub_curve25519": "B" * 44,
                "ik_pub_ed25519":   "B" * 44,
                "spk_pub":          "B" * 44,
                "spk_sig":          "C" * 88,
            })

            # A receives key.rotate.ack
            ack = await comm_a.receive_json_from()
            self.assertEqual(ack.get("type"), "key.rotate.ack",
                             f"Expected key.rotate.ack from A, got: {ack}")

            # The channel layer should have the pm_key_rotate_alarm for B's group
            event = await channel_layer.receive(test_channel)
            self.assertEqual(event.get("type"), "pm_key_rotate_alarm",
                             f"Expected pm_key_rotate_alarm, got: {event}")
            payload = event.get("payload", {})
            self.assertEqual(payload.get("reason"), "key_rotation",
                             f"Expected reason='key_rotation', got: {payload}")
            self.assertEqual(payload.get("user_id"), self.user_a.pk,
                             "Alarm payload must carry the rotating user's ID")
        finally:
            await comm_a.disconnect()
            await channel_layer.group_discard(peer_group, test_channel)

    async def test_peer_connected_receives_alarm_via_websocket(self):
        """
        End-to-end: B is connected when A rotates keys. B's WS must
        deliver a pm.key_rotate_alarm JSON event.
        """
        # Connect B first (listening on their own group)
        comm_b = WebsocketCommunicator(_app(), f"/ws/pm/{self.user_a.pk}/")
        comm_b.scope["user"] = self.user_b
        connected_b, _ = await comm_b.connect()
        self.assertTrue(connected_b)

        # Connect A (will rotate keys toward B)
        comm_a = WebsocketCommunicator(_app(), f"/ws/pm/{self.user_b.pk}/")
        comm_a.scope["user"] = self.user_a
        connected_a, _ = await comm_a.connect()
        self.assertTrue(connected_a)

        try:
            await comm_a.send_json_to({
                "type":             "key.rotate",
                "ik_pub_curve25519": "E" * 44,
                "ik_pub_ed25519":   "E" * 44,
                "spk_pub":          "E" * 44,
                "spk_sig":          "F" * 88,
            })

            # A gets ack
            ack = await comm_a.receive_json_from()
            self.assertEqual(ack.get("type"), "key.rotate.ack")

            # B should receive the key_rotate_alarm via WS
            alarm = await comm_b.receive_json_from()
            self.assertEqual(alarm.get("type"), "pm.key_rotate_alarm",
                             f"B expected pm.key_rotate_alarm, got: {alarm}")
            payload = alarm.get("payload", {})
            self.assertEqual(payload.get("reason"), "key_rotation")
            self.assertEqual(payload.get("user_id"), self.user_a.pk)
        finally:
            await comm_a.disconnect()
            await comm_b.disconnect()

    async def test_key_rotate_updates_server_side_identity(self):
        """
        After A's key.rotate, IdentityKey for A is updated in the DB
        with the new public keys.
        """
        comm_a = WebsocketCommunicator(_app(), f"/ws/pm/{self.user_b.pk}/")
        comm_a.scope["user"] = self.user_a
        await comm_a.connect()
        try:
            new_ik_curve = "N" * 44
            new_ik_ed    = "M" * 44
            await comm_a.send_json_to({
                "type":             "key.rotate",
                "ik_pub_curve25519": new_ik_curve,
                "ik_pub_ed25519":   new_ik_ed,
                "spk_pub":          "S" * 44,
                "spk_sig":          "G" * 88,
            })
            await comm_a.receive_json_from()  # consume ack

            ik = await IdentityKey.objects.aget(user=self.user_a)
            self.assertEqual(ik.ik_pub_curve25519, new_ik_curve,
                             "ik_pub_curve25519 should be updated after key.rotate")
            self.assertEqual(ik.ik_pub_ed25519, new_ik_ed,
                             "ik_pub_ed25519 should be updated after key.rotate")
        finally:
            await comm_a.disconnect()

    async def test_first_publish_does_NOT_alarm_peer(self):
        """
        When a user has NO prior IdentityKey row and sends key.rotate for the
        first time, the peer's channel group must NOT receive a
        pm_key_rotate_alarm event — this is a first publish, not a rotation.

        The sender must still receive key.rotate.ack, and the new IdentityKey
        row must be present in the DB after the call.
        """
        # Delete A's existing identity key to simulate a first-time publish.
        await IdentityKey.objects.filter(user=self.user_a).adelete()

        channel_layer = get_channel_layer()
        peer_group = f"pm_user_{self.user_b.pk}"
        test_channel = "test_first_publish_no_alarm_ch"

        await channel_layer.group_add(peer_group, test_channel)

        comm_a = WebsocketCommunicator(_app(), f"/ws/pm/{self.user_b.pk}/")
        comm_a.scope["user"] = self.user_a
        connected, _ = await comm_a.connect()
        self.assertTrue(connected)

        try:
            new_curve = "Z" * 44
            await comm_a.send_json_to({
                "type":             "key.rotate",
                "ik_pub_curve25519": new_curve,
                "ik_pub_ed25519":   "Z" * 44,
                "spk_pub":          "Z" * 44,
                "spk_sig":          "Y" * 88,
            })

            # A must receive key.rotate.ack regardless of rotation status.
            ack = await comm_a.receive_json_from()
            self.assertEqual(ack.get("type"), "key.rotate.ack",
                             f"Expected key.rotate.ack from A on first publish, got: {ack}")

            # The peer channel must NOT receive any alarm within a short window.
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    channel_layer.receive(test_channel),
                    timeout=0.5,
                )

            # The new IdentityKey row must exist in the DB.
            ik = await IdentityKey.objects.aget(user=self.user_a)
            self.assertEqual(ik.ik_pub_curve25519, new_curve,
                             "IdentityKey row must be created on first publish")
        finally:
            await comm_a.disconnect()
            await channel_layer.group_discard(peer_group, test_channel)

    async def test_identical_republish_does_NOT_alarm_peer(self):
        """
        When a user re-publishes the exact same Curve25519 identity key that is
        already stored (idempotent re-publish), the peer's channel group must NOT
        receive a pm_key_rotate_alarm event.

        setUp seeds A with ik_pub_curve25519="A"*44. This test sends the same
        value, verifying that byte-for-byte equality suppresses the alarm.

        The sender must still receive key.rotate.ack.
        """
        channel_layer = get_channel_layer()
        peer_group = f"pm_user_{self.user_b.pk}"
        test_channel = "test_identical_republish_no_alarm_ch"

        await channel_layer.group_add(peer_group, test_channel)

        comm_a = WebsocketCommunicator(_app(), f"/ws/pm/{self.user_b.pk}/")
        comm_a.scope["user"] = self.user_a
        connected, _ = await comm_a.connect()
        self.assertTrue(connected)

        try:
            # Send the SAME curve25519 key that setUp seeded ("A" * 44).
            await comm_a.send_json_to({
                "type":             "key.rotate",
                "ik_pub_curve25519": "A" * 44,
                "ik_pub_ed25519":   "A" * 44,
                "spk_pub":          "A" * 44,
                "spk_sig":          "B" * 88,
            })

            # A must receive key.rotate.ack regardless.
            ack = await comm_a.receive_json_from()
            self.assertEqual(ack.get("type"), "key.rotate.ack",
                             f"Expected key.rotate.ack from A on identical republish, got: {ack}")

            # The peer channel must NOT receive any alarm within a short window.
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    channel_layer.receive(test_channel),
                    timeout=0.5,
                )
        finally:
            await comm_a.disconnect()
            await channel_layer.group_discard(peer_group, test_channel)
