"""
test_rate_limits.py

Verifies rate limiting for PRIVATE_MESSAGES consumer actions.
Uses Django's locmem cache (no Redis required).
Tests that exceeding the cap returns type=error code=rate_limited with
retry_after set, and that DB rows are NOT created for over-cap calls.
"""

from unittest.mock import patch
from django.test import TestCase, TransactionTestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from channels.testing import WebsocketCommunicator
from django.urls import re_path
from channels.routing import URLRouter

from PRIVATE_MESSAGES.consumers import PrivateMessageConsumer
from PRIVATE_MESSAGES.models import EncryptedEnvelope
from PRIVATE_MESSAGES import rate_limit as rl

UserModel = get_user_model()


def _make_user(username: str):
    return UserModel.objects.create_user(username=username, password="testpass123!")


def _make_friends(user_a, user_b):
    from FRIEND.models import Friend
    Friend.objects.get_or_create(from_user=user_a, to_user=user_b)
    Friend.objects.get_or_create(from_user=user_b, to_user=user_a)


def _make_identity(user):
    from PRIVATE_MESSAGES.models import IdentityKey, SignedPreKey
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


async def _comm(user, peer_id):
    c = WebsocketCommunicator(_app(), f"/ws/pm/{peer_id}/")
    c.scope["user"] = user
    return c


class RateLimitUnitTest(TestCase):
    """
    Unit-test rate_limit.check() directly using the locmem cache.
    Confirms that exceeding the cap returns (False, 0, retry_after > 0)
    and that staying within the cap returns (True, remaining >= 0, 0).
    """

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_envelope_send_cap_at_60(self):
        user_id = 9999001
        action = "envelope.send"
        max_req, _ = rl._LIMITS[action]

        for i in range(max_req):
            ok, remaining, retry_after = rl.check(action, user_id)
            self.assertTrue(ok, f"Request {i+1} should be allowed (cap={max_req})")
            self.assertEqual(retry_after, 0)

        # 61st request — must be denied
        ok, remaining, retry_after = rl.check(action, user_id)
        self.assertFalse(ok, "61st envelope.send must be denied")
        self.assertEqual(remaining, 0)
        self.assertGreater(retry_after, 0, "retry_after must be > 0 when denied")

    def test_session_init_cap_at_20(self):
        user_id = 9999002
        action = "session.init"
        max_req, _ = rl._LIMITS[action]

        for i in range(max_req):
            ok, _, _ = rl.check(action, user_id)
            self.assertTrue(ok, f"Request {i+1} should be allowed")

        ok, remaining, retry_after = rl.check(action, user_id)
        self.assertFalse(ok, "Over-cap session.init must be denied")
        self.assertGreater(retry_after, 0)

    def test_prekey_publish_cap_at_3(self):
        user_id = 9999003
        action = "prekey.publish"
        max_req, _ = rl._LIMITS[action]

        for i in range(max_req):
            ok, _, _ = rl.check(action, user_id)
            self.assertTrue(ok, f"Request {i+1} should be allowed")

        ok, _, retry_after = rl.check(action, user_id)
        self.assertFalse(ok)
        self.assertGreater(retry_after, 0)

    def test_key_rotate_cap_at_1(self):
        user_id = 9999004
        action = "key.rotate"
        ok_first, _, _ = rl.check(action, user_id)
        self.assertTrue(ok_first, "First key.rotate must be allowed")

        ok_second, _, retry_after = rl.check(action, user_id)
        self.assertFalse(ok_second, "Second key.rotate within 6h must be denied")
        self.assertGreater(retry_after, 0)

    def test_prekey_request_cap_at_30(self):
        user_id = 9999005
        action = "prekey.request"
        max_req, _ = rl._LIMITS[action]

        for i in range(max_req):
            ok, _, _ = rl.check(action, user_id)
            self.assertTrue(ok)

        ok, _, retry_after = rl.check(action, user_id)
        self.assertFalse(ok)
        self.assertGreater(retry_after, 0)

    def test_unknown_action_is_allowed_unconditionally(self):
        ok, remaining, retry_after = rl.check("nonexistent.action", 1)
        self.assertTrue(ok)
        self.assertEqual(retry_after, 0)

    def test_different_users_have_independent_counters(self):
        """User A exhausting rate limit must not affect user B."""
        action = "envelope.send"
        max_req, _ = rl._LIMITS[action]
        user_a = 9998001
        user_b = 9998002

        for _ in range(max_req + 1):
            rl.check(action, user_a)

        ok_b, _, _ = rl.check(action, user_b)
        self.assertTrue(ok_b, "User B's rate limit must be independent of user A's")


class RateLimitEnvelopeSendNoDBSideEffect(TransactionTestCase):
    """
    Confirm that once the cap is hit, additional envelope.send calls
    over the WS do not create EncryptedEnvelope rows.
    """

    def setUp(self):
        cache.clear()
        self.user_a = _make_user("rl_ws_a")
        self.user_b = _make_user("rl_ws_b")
        _make_friends(self.user_a, self.user_b)
        _make_identity(self.user_a)
        _make_identity(self.user_b)

    def tearDown(self):
        cache.clear()

    async def test_over_cap_envelope_send_has_no_db_side_effect(self):
        """Send 62 envelopes; first 60 succeed, 61st and 62nd are denied with
        rate_limited error and must NOT create EncryptedEnvelope rows."""
        comm = await _comm(self.user_a, self.user_b.pk)
        connected, _ = await comm.connect()
        self.assertTrue(connected)

        # Burn 60 allowed requests
        MAX = 60
        try:
            for i in range(MAX):
                await comm.send_json_to({
                    "type":          "envelope.send",
                    "ciphertext_b64": f"ENVELOPE_{i:03d}",
                    "message_type":  1,
                })
                resp = await comm.receive_json_from()
                self.assertEqual(resp.get("type"), "envelope.send.ack",
                                 f"Request {i+1} should succeed")

            row_count_at_cap = await EncryptedEnvelope.objects.filter(
                sender=self.user_a
            ).acount()
            self.assertEqual(row_count_at_cap, MAX,
                             f"Should have exactly {MAX} rows at cap")

            # 61st — must be denied
            await comm.send_json_to({
                "type":          "envelope.send",
                "ciphertext_b64": "ENVELOPE_OVER_CAP",
                "message_type":  1,
            })
            resp_61 = await comm.receive_json_from()
            self.assertEqual(resp_61.get("type"), "error")
            self.assertEqual(resp_61.get("code"), "rate_limited")
            self.assertIn("retry_after", resp_61,
                          "retry_after must be present in rate_limited response")
            self.assertGreater(resp_61.get("retry_after", 0), 0)

            # DB count must NOT increase
            row_count_after_deny = await EncryptedEnvelope.objects.filter(
                sender=self.user_a
            ).acount()
            self.assertEqual(row_count_after_deny, MAX,
                             "Over-cap request must not create a DB row")
        finally:
            await comm.disconnect()
