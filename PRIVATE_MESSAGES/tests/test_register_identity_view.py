"""
test_register_identity_view.py

Tests for POST /pm/register-identity/ (register_identity_view).

Coverage:
1. Anonymous user -> 302 redirect to login.
2. GET by authenticated user -> 405 Method Not Allowed.
3. Happy path first publish: valid body, 200 {"ok": True, "otpks_inserted": 3}, DB rows present.
4. Happy path re-publish (idempotent): two identical calls both succeed; still exactly
   one IdentityKey + one SignedPreKey + 3 OTPKs (not 6).
5. Invalid JSON body -> 400 {"error": "invalid_json"}.
6. Missing identity field -> 400 {"error": "invalid_payload", ...}.
7. OTPK batch too large (>100) -> 400 {"error": "invalid_payload", ...}.
8. Empty OTPK list -> 400 {"error": "invalid_payload", ...}.
9. Key field too long (ik_pub_curve25519 of length 65) -> 400 {"error": "invalid_payload", ...}.
10. CSRF token absent with CSRF enforcement enabled -> 403.
"""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from PRIVATE_MESSAGES.models import IdentityKey, OneTimePreKey, SignedPreKey

UserModel = get_user_model()

_URL = None  # resolved lazily via reverse() in setUp to avoid import-time URL resolution


def _make_user(username: str):
    return UserModel.objects.create_user(username=username, password="testpass123!")


def _valid_body(num_otpks: int = 3) -> dict:
    """Return a minimal valid request body for register_identity_view."""
    return {
        "ik_pub_curve25519": "A" * 44,
        "ik_pub_ed25519": "B" * 44,
        "spk_pub": "C" * 44,
        "spk_sig": "D" * 88,
        "one_time_prekeys": [
            {"otpk_id": f"otpk_{i:03d}", "otpk_pub": "E" * 44}
            for i in range(num_otpks)
        ],
    }


def _post_json(client: Client, url: str, body: dict) -> object:
    return client.post(
        url,
        data=json.dumps(body),
        content_type="application/json",
        HTTP_HOST="127.0.0.1",
    )


class RegisterIdentityViewAuthTest(TestCase):
    """Authentication and HTTP-method gate tests."""

    def setUp(self):
        self.user = _make_user("reg_auth_user")
        self.url = reverse("private_messages:pm_register_identity")

    def test_anonymous_post_redirects_to_login(self):
        """Unauthenticated POST must redirect (302) to the login page."""
        anon_client = Client()
        response = _post_json(anon_client, self.url, _valid_body())
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"].lower())

    def test_get_returns_405(self):
        """GET by an authenticated user must return 405 Method Not Allowed."""
        self.client.force_login(self.user)
        response = self.client.get(self.url, HTTP_HOST="127.0.0.1")
        self.assertEqual(response.status_code, 405)


class RegisterIdentityViewHappyPathTest(TestCase):
    """Happy-path and idempotency tests."""

    def setUp(self):
        self.user = _make_user("reg_happy_user")
        self.url = reverse("private_messages:pm_register_identity")
        self.client.force_login(self.user)

    def test_first_publish_returns_200_with_otpks_inserted(self):
        """Valid first-publish: 200 with ok=True and otpks_inserted=3; DB rows present."""
        response = _post_json(self.client, self.url, _valid_body(num_otpks=3))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"), f"Expected ok=True, got: {data}")
        self.assertEqual(data.get("otpks_inserted"), 3,
                         f"Expected otpks_inserted=3, got: {data}")

        # Verify DB state.
        self.assertEqual(
            IdentityKey.objects.filter(user_id=self.user.id).count(), 1,
            "Exactly one IdentityKey row must exist after first publish"
        )
        self.assertEqual(
            SignedPreKey.objects.filter(user_id=self.user.id).count(), 1,
            "Exactly one SignedPreKey row must exist after first publish"
        )
        self.assertEqual(
            OneTimePreKey.objects.filter(user_id=self.user.id).count(), 3,
            "Exactly 3 OTPK rows must exist after first publish"
        )

    def test_re_publish_is_idempotent(self):
        """
        Calling the endpoint twice with identical bodies must succeed both times.

        After the second call:
        - Exactly one IdentityKey row (not two).
        - Exactly one SignedPreKey row (not two).
        - Exactly 3 OTPK rows (register_identity wipes the pool before each publish;
          publish_one_time_prekeys then inserts the new batch, so count stays 3, not 6).
        """
        body = _valid_body(num_otpks=3)

        # First call.
        r1 = _post_json(self.client, self.url, body)
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json().get("ok"))

        # Second call — identical payload.
        r2 = _post_json(self.client, self.url, body)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get("ok"))

        # Exactly one of each key row after both calls.
        self.assertEqual(
            IdentityKey.objects.filter(user_id=self.user.id).count(), 1,
            "Re-publish must not create a second IdentityKey row"
        )
        self.assertEqual(
            SignedPreKey.objects.filter(user_id=self.user.id).count(), 1,
            "Re-publish must not create a second SignedPreKey row"
        )
        self.assertEqual(
            OneTimePreKey.objects.filter(user_id=self.user.id).count(), 3,
            "OTPK pool must contain exactly 3 entries after two identical publishes, not 6"
        )


class RegisterIdentityViewValidationTest(TestCase):
    """Input-validation rejection tests."""

    def setUp(self):
        self.user = _make_user("reg_validation_user")
        self.url = reverse("private_messages:pm_register_identity")
        self.client.force_login(self.user)

    def test_invalid_json_body_returns_400(self):
        """A body that is not valid JSON must return 400 with error=invalid_json."""
        response = self.client.post(
            self.url,
            data=b"this is not json {{{",
            content_type="application/json",
            HTTP_HOST="127.0.0.1",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data.get("error"), "invalid_json")

    def test_missing_identity_field_returns_400(self):
        """Omitting a required key-material field must return 400 with error=invalid_payload."""
        body = _valid_body()
        del body["ik_pub_ed25519"]
        response = _post_json(self.client, self.url, body)
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data.get("error"), "invalid_payload")
        self.assertIn("ik_pub_ed25519", data.get("detail", ""))

    def test_otpk_batch_too_large_returns_400(self):
        """A one_time_prekeys list with more than 100 entries must return 400."""
        body = _valid_body(num_otpks=101)
        response = _post_json(self.client, self.url, body)
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data.get("error"), "invalid_payload")

    def test_empty_otpk_list_returns_400(self):
        """An empty one_time_prekeys list must return 400 with error=invalid_payload."""
        body = _valid_body()
        body["one_time_prekeys"] = []
        response = _post_json(self.client, self.url, body)
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data.get("error"), "invalid_payload")

    def test_key_field_too_long_returns_400(self):
        """ik_pub_curve25519 of length 65 (> _MAX_KEY_FIELD_LEN=64) must return 400."""
        body = _valid_body()
        body["ik_pub_curve25519"] = "A" * 65
        response = _post_json(self.client, self.url, body)
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data.get("error"), "invalid_payload")
        self.assertIn("ik_pub_curve25519", data.get("detail", ""))


class RegisterIdentityViewCsrfTest(TestCase):
    """CSRF enforcement test."""

    def setUp(self):
        self.user = _make_user("reg_csrf_user")
        self.url = reverse("private_messages:pm_register_identity")

    def test_post_without_csrf_token_returns_403(self):
        """
        A POST from a client with CSRF enforcement enabled and no CSRF token
        must be rejected with 403 Forbidden.
        """
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        response = csrf_client.post(
            self.url,
            data=json.dumps(_valid_body()),
            content_type="application/json",
            HTTP_HOST="127.0.0.1",
            # Deliberately omit the CSRF token.
        )
        self.assertEqual(response.status_code, 403)
