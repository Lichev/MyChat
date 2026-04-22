"""
test_key_rotation_fanout.py

H1: Verifies that _handle_key_rotate fans out pm_key_rotate_alarm to ALL
peers with PrivateSession state, not just the single peer the socket is
connected to.
"""

from unittest.mock import AsyncMock, patch, MagicMock

from django.test import TransactionTestCase
from django.contrib.auth import get_user_model

from PRIVATE_MESSAGES.models import PrivateSession
from PRIVATE_MESSAGES import services

UserModel = get_user_model()


def _make_user(username: str) -> UserModel:
    return UserModel.objects.create_user(username=username, password="testpass123!")


class KeyRotationFanoutTest(TransactionTestCase):
    """H1: Key rotation alarm must reach every peer with a PrivateSession."""

    def setUp(self):
        self.alice = _make_user("fanout_alice")
        self.bob = _make_user("fanout_bob")
        self.carol = _make_user("fanout_carol")

        # Ensure canonical order (lo < hi) for PrivateSession.
        lo, hi = sorted([self.alice.pk, self.bob.pk])
        PrivateSession.objects.create(user_a_id=lo, user_b_id=hi)

        lo2, hi2 = sorted([self.alice.pk, self.carol.pk])
        PrivateSession.objects.create(user_a_id=lo2, user_b_id=hi2)

    def test_active_session_peer_ids_returns_both_peers(self):
        """active_session_peer_ids_for must return Bob and Carol for Alice."""
        peer_ids = services.active_session_peer_ids_for(self.alice.pk)
        self.assertIn(self.bob.pk, peer_ids)
        self.assertIn(self.carol.pk, peer_ids)
        self.assertNotIn(self.alice.pk, peer_ids)

    def test_rotation_alarms_all_active_peers(self):
        """
        _handle_key_rotate must fan out pm_key_rotate_alarm to Bob and Carol
        (all PrivateSession peers), not only the peer the socket is open with.
        """
        from channels.routing import URLRouter
        from channels.testing import WebsocketCommunicator
        from django.urls import re_path
        from PRIVATE_MESSAGES.consumers import PrivateMessageConsumer

        # We test the service layer directly since WebSocket channel-layer
        # fan-out requires a full channel layer stack that is complex to
        # replicate in a unit test. Instead, patch the channel_layer on a
        # mock consumer and call the handler directly.

        import asyncio

        sent_groups = []

        async def fake_group_send(group, message):
            sent_groups.append((group, message))

        # Build a minimal fake consumer with the attributes _handle_key_rotate needs.
        consumer = MagicMock()
        consumer.user_id = self.alice.pk
        consumer.peer_id = self.bob.pk
        consumer.channel_layer = MagicMock()
        consumer.channel_layer.group_send = fake_group_send
        consumer.send_json = AsyncMock()
        consumer._send_error = AsyncMock()
        consumer._send_rate_limit_error = AsyncMock()

        # Patch rate limit to always allow and register_identity to return is_rotation=True.
        with patch('PRIVATE_MESSAGES.consumers.rl.check', return_value=(True, 10, 0)), \
             patch('PRIVATE_MESSAGES.consumers.sync_to_async') as mock_s2a:

            # sync_to_async is used twice in _handle_key_rotate:
            # 1st call: services.register_identity → returns (ik, True)
            # 2nd call: services.active_session_peer_ids_for → returns [bob_id, carol_id]
            call_count = [0]

            async def fake_sync_to_async_call(*args, **kwargs):
                # This is called as sync_to_async(fn)(args)
                pass

            import PRIVATE_MESSAGES.consumers as consumers_mod

            original_handle = consumers_mod.PrivateMessageConsumer._handle_key_rotate

            # Patch sync_to_async to return awaitable fakes.
            from asgiref.sync import sync_to_async as real_s2a

            def patched_s2a(fn):
                if fn == services.register_identity:
                    async def _reg(*a, **kw):
                        return (MagicMock(), True)  # is_rotation=True
                    return _reg
                elif fn == services.active_session_peer_ids_for:
                    async def _peers(*a, **kw):
                        return [self.bob.pk, self.carol.pk]
                    return _peers
                return real_s2a(fn)

            mock_s2a.side_effect = patched_s2a

            content = {
                "ik_pub_curve25519": "A" * 44,
                "ik_pub_ed25519": "B" * 44,
                "spk_pub": "C" * 44,
                "spk_sig": "D" * 88,
            }

            asyncio.get_event_loop().run_until_complete(
                original_handle(consumer, content)
            )

        # Both Bob and Carol must have received the alarm.
        alarm_groups = [g for g, m in sent_groups if m.get("type") == "pm_key_rotate_alarm"]
        self.assertIn(f"pm_user_{self.bob.pk}", alarm_groups,
                      f"Bob should have received alarm; got groups: {alarm_groups}")
        self.assertIn(f"pm_user_{self.carol.pk}", alarm_groups,
                      f"Carol should have received alarm; got groups: {alarm_groups}")

        # Alice must NOT receive the alarm.
        self.assertNotIn(f"pm_user_{self.alice.pk}", alarm_groups,
                         "Alice (the rotating user) must not receive her own alarm.")
