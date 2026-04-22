"""
test_peer_registered_push.py

Fix 3: When a user first-publishes their identity via services.register_identity,
every friend with an open WS should receive a `peer.registered` event so their
client can cancel the retry backoff and re-initiate X3DH immediately.

Rotations (is_rotation=True) must NOT trigger this push — peers get
`pm_key_rotate_alarm` instead, which is a stronger signal that forces session
replacement rather than retry.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TransactionTestCase

from FRIEND.models import Friend
from PRIVATE_MESSAGES import services
from PRIVATE_MESSAGES.models import IdentityKey

UserModel = get_user_model()


def _make_user(username: str) -> UserModel:
    return UserModel.objects.create_user(username=username, password="testpass123!")


def _make_friends(u1: UserModel, u2: UserModel) -> None:
    """Create bilateral Friend rows (MyChat stores two per friendship)."""
    Friend.objects.create(from_user=u1, to_user=u2)
    Friend.objects.create(from_user=u2, to_user=u1)


class PeerRegisteredPushTest(TransactionTestCase):
    """First-publish must fan out peer.registered to each friend."""

    def setUp(self):
        self.alice = _make_user("pr_alice")
        self.bob = _make_user("pr_bob")
        self.carol = _make_user("pr_carol")
        _make_friends(self.alice, self.bob)
        _make_friends(self.alice, self.carol)

    def test_first_publish_fans_out_to_all_friends(self):
        """Alice's first key publish notifies Bob + Carol but not Alice."""
        sent = []

        async def fake_group_send(group, event):
            sent.append((group, event))

        with patch(
            "PRIVATE_MESSAGES.services.get_channel_layer"
        ) as mock_get_layer:
            mock_layer = mock_get_layer.return_value
            mock_layer.group_send = fake_group_send
            with transaction.atomic():
                services.register_identity(
                    user_id=self.alice.pk,
                    ik_curve="a" * 43,
                    ik_ed="b" * 43,
                    spk_pub="a" * 43,
                    spk_sig="c" * 86,
                )

        groups = [g for g, _ in sent]
        self.assertIn(f"pm_user_{self.bob.pk}", groups)
        self.assertIn(f"pm_user_{self.carol.pk}", groups)
        self.assertNotIn(f"pm_user_{self.alice.pk}", groups)

        for _, event in sent:
            self.assertEqual(event["type"], "pm_peer_registered")
            self.assertEqual(event["payload"]["peer_id"], self.alice.pk)

    def test_rotation_does_not_trigger_peer_registered_push(self):
        """is_rotation=True path emits key_rotate_alarm — NOT peer.registered."""
        # Seed Alice with an existing identity so the next register is a rotation.
        IdentityKey.objects.create(
            user_id=self.alice.pk,
            ik_pub_curve25519="x" * 43,
            ik_pub_ed25519="y" * 43,
        )

        sent = []

        async def fake_group_send(group, event):
            sent.append((group, event))

        with patch(
            "PRIVATE_MESSAGES.services.get_channel_layer"
        ) as mock_get_layer:
            mock_layer = mock_get_layer.return_value
            mock_layer.group_send = fake_group_send
            with transaction.atomic():
                _, is_rotation = services.register_identity(
                    user_id=self.alice.pk,
                    ik_curve="z" * 43,  # different from prior "x"*43 → rotation
                    ik_ed="w" * 43,
                    spk_pub="z" * 43,
                    spk_sig="q" * 86,
                )

        self.assertTrue(is_rotation)
        peer_registered_events = [
            e for _, e in sent if e.get("type") == "pm_peer_registered"
        ]
        self.assertEqual(
            peer_registered_events,
            [],
            "Rotation must not emit peer.registered — key_rotate_alarm handles it",
        )
