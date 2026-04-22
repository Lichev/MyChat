"""
test_panic_wipe.py

Tests panic_wipe_view:
- POST by authenticated user wipes all pm_* rows for that user.
- GET → 405. Anonymous POST → 302 (login redirect).
- Peer's data is untouched.
- pm.wipe is broadcast to peer's channel group (via InMemoryChannelLayer).
"""

from django.test import TransactionTestCase, Client
from asgiref.sync import sync_to_async
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from PRIVATE_MESSAGES.models import (
    EncryptedEnvelope, IdentityKey, OneTimePreKey, PrivateSession, SignedPreKey
)

UserModel = get_user_model()


def _make_user(username: str):
    return UserModel.objects.create_user(username=username, password="testpass123!")


def _make_friends(user_a, user_b):
    from FRIEND.models import Friend
    Friend.objects.get_or_create(from_user=user_a, to_user=user_b)
    Friend.objects.get_or_create(from_user=user_b, to_user=user_a)


def _register_identity(user):
    ik = IdentityKey.objects.create(
        user=user,
        ik_pub_curve25519="A" * 44,
        ik_pub_ed25519="A" * 44,
    )
    SignedPreKey.objects.create(
        user=user, spk_id=1,
        spk_pub="A" * 44, spk_sig="B" * 88, is_active=True,
    )
    OneTimePreKey.objects.create(user=user, otpk_id="otk001", otpk_pub="C" * 44)
    OneTimePreKey.objects.create(user=user, otpk_id="otk002", otpk_pub="D" * 44)
    return ik


def _create_envelope(sender, recipient):
    return EncryptedEnvelope.objects.create(
        sender=sender,
        recipient=recipient,
        ciphertext_b64="PENDING_ENVELOPE",
        message_type=1,
        expires_at=timezone.now() + timedelta(days=7),
    )


def _create_session(user_a, user_b):
    lo, hi = (user_a.pk, user_b.pk) if user_a.pk < user_b.pk else (user_b.pk, user_a.pk)
    return PrivateSession.objects.get_or_create(user_a_id=lo, user_b_id=hi)[0]


class PanicWipeAuthTest(TransactionTestCase):
    """HTTP method and auth gate tests (sync Django test client)."""

    def setUp(self):
        self.user = _make_user("wipe_auth_user")
        self.client = Client()

    def test_get_returns_405(self):
        self.client.force_login(self.user)
        response = self.client.get("/pm/panic-wipe/", HTTP_HOST="127.0.0.1")
        self.assertEqual(response.status_code, 405,
                         "GET to panic-wipe must return 405 Method Not Allowed")

    def test_anonymous_post_redirects_to_login(self):
        # Explicitly use an anonymous client
        anon_client = Client()
        response = anon_client.post(
            "/pm/panic-wipe/",
            HTTP_HOST="127.0.0.1",
        )
        self.assertEqual(response.status_code, 302,
                         "Anonymous POST must redirect (302) to login")
        self.assertIn("login", response["Location"].lower(),
                      "Redirect must point to login page")


class PanicWipeFunctionalTest(TransactionTestCase):
    """
    Authenticated POST wipes all pm_* rows for user A.
    Peer B's data is untouched.
    """

    def setUp(self):
        self.user_a = _make_user("wipe_a")
        self.user_b = _make_user("wipe_b")
        _make_friends(self.user_a, self.user_b)
        _register_identity(self.user_a)
        _register_identity(self.user_b)
        _create_envelope(self.user_a, self.user_b)
        _create_envelope(self.user_b, self.user_a)
        _create_session(self.user_a, self.user_b)
        self.client = Client()
        self.client.force_login(self.user_a)

    def test_panic_wipe_returns_200_json_ok(self):
        response = self.client.post("/pm/panic-wipe/", HTTP_HOST="127.0.0.1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"), f"Expected {{ok: true}}, got: {data}")

    def test_all_pm_rows_for_user_a_deleted(self):
        self.client.post("/pm/panic-wipe/", HTTP_HOST="127.0.0.1")

        # IK
        self.assertFalse(
            IdentityKey.objects.filter(user=self.user_a).exists(),
            "A's IdentityKey should be deleted by panic wipe"
        )
        # SPK
        self.assertFalse(
            SignedPreKey.objects.filter(user=self.user_a).exists(),
            "A's SignedPreKey should be deleted by panic wipe"
        )
        # OTPK
        self.assertFalse(
            OneTimePreKey.objects.filter(user=self.user_a).exists(),
            "A's OneTimePreKeys should be deleted by panic wipe"
        )
        # Sent envelopes
        self.assertFalse(
            EncryptedEnvelope.objects.filter(sender=self.user_a).exists(),
            "A's sent envelopes should be deleted by panic wipe"
        )
        # Received envelopes
        self.assertFalse(
            EncryptedEnvelope.objects.filter(recipient=self.user_a).exists(),
            "A's received envelopes should be deleted by panic wipe"
        )
        # Session
        from django.db.models import Q
        self.assertFalse(
            PrivateSession.objects.filter(
                Q(user_a=self.user_a) | Q(user_b=self.user_a)
            ).exists(),
            "A's session record should be deleted by panic wipe"
        )

    def test_peer_b_data_untouched_after_a_wipes(self):
        self.client.post("/pm/panic-wipe/", HTTP_HOST="127.0.0.1")

        # B's IK should still exist
        self.assertTrue(
            IdentityKey.objects.filter(user=self.user_b).exists(),
            "B's IdentityKey must NOT be deleted by A's panic wipe"
        )
        # B's OTPKs should still exist
        self.assertTrue(
            OneTimePreKey.objects.filter(user=self.user_b).exists(),
            "B's OTPKs must NOT be deleted by A's panic wipe"
        )


class PanicWipeBroadcastTest(TransactionTestCase):
    """
    Verify that a pm.wipe event is broadcast to the peer's channel group.
    Uses InMemoryChannelLayer directly.
    """

    def setUp(self):
        self.user_a = _make_user("wipe_broadcast_a")
        self.user_b = _make_user("wipe_broadcast_b")
        _make_friends(self.user_a, self.user_b)
        _register_identity(self.user_a)
        _register_identity(self.user_b)
        _create_session(self.user_a, self.user_b)
        self.client = Client()
        self.client.force_login(self.user_a)

    async def test_pm_wipe_event_broadcast_to_peer_group(self):
        """
        After POST /pm/panic-wipe/, the channel layer should have dispatched
        a pm_wipe event to B's group (pm_user_<B.pk>).
        We subscribe a test channel to B's group and verify receipt.
        """
        channel_layer = get_channel_layer()
        # Subscribe a dedicated test channel to B's group
        test_channel = "test_wipe_channel_for_b"
        peer_group = f"pm_user_{self.user_b.pk}"
        await channel_layer.group_add(peer_group, test_channel)

        # POST the panic wipe (sync path via sync_to_async)
        post = sync_to_async(self.client.post)
        response = await post("/pm/panic-wipe/", HTTP_HOST="127.0.0.1")
        self.assertEqual(response.status_code, 200)

        # Receive the pm_wipe event from B's group
        try:
            event = await channel_layer.receive(test_channel)
            self.assertEqual(event.get("type"), "pm_wipe",
                             f"Expected pm_wipe event, got: {event}")
            self.assertEqual(event.get("peer_id"), self.user_a.pk,
                             "pm_wipe event must carry the wiping user's ID as peer_id")
        except Exception as exc:
            self.fail(f"Did not receive pm_wipe broadcast on peer's group: {exc}")
        finally:
            await channel_layer.group_discard(peer_group, test_channel)
