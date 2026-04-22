"""
test_recovery.py

Verifies that RecoverAccountView no longer scans Session.objects.all() (C6 fix).
The current implementation uses Session.objects.filter(expire_date__gt=...) —
never the full-table scan variant.
"""

from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.test import TestCase
from django.urls import reverse

UserModel = get_user_model()

_RECOVERY_URL = "/accounts/recover/"


class SessionScanTest(TestCase):
    """C6: the recovery flow must not invoke Session.objects.all()."""

    def setUp(self):
        self.user = UserModel.objects.create_user(
            username="recover_testuser",
            password="OldPassword1!",
        )
        raw_key = "my-super-secret-recovery-key"
        self.user.recovery_key_hash = make_password(raw_key)
        self.user.save(update_fields=["recovery_key_hash"])
        self.raw_key = raw_key

    def test_session_invalidation_does_not_scan_all_sessions(self):
        """Session.objects.all must never be called during account recovery."""

        # Patch Session.objects.all to raise AssertionError if invoked.
        sentinel = MagicMock(side_effect=AssertionError(
            "Session.objects.all() called — full-table scan is forbidden in RecoverAccountView"
        ))

        with patch("django.contrib.sessions.models.Session.objects.all", sentinel):
            response = self.client.post(_RECOVERY_URL, {
                "username": self.user.username,
                "recovery_key": self.raw_key,
                "new_password1": "NewSecurePass99!",
                "new_password2": "NewSecurePass99!",
            })

        # If we reach here, Session.objects.all was NOT called (no AssertionError raised).
        # A successful recovery redirects to login.
        self.assertIn(response.status_code, [200, 302],
                      f"Unexpected status: {response.status_code}")

    def test_wrong_recovery_key_does_not_scan_all_sessions(self):
        """Even on failure, the view must not invoke Session.objects.all."""
        sentinel = MagicMock(side_effect=AssertionError(
            "Session.objects.all() called — forbidden"
        ))

        with patch("django.contrib.sessions.models.Session.objects.all", sentinel):
            response = self.client.post(_RECOVERY_URL, {
                "username": self.user.username,
                "recovery_key": "wrong-key",
                "new_password1": "NewSecurePass99!",
                "new_password2": "NewSecurePass99!",
            })

        self.assertEqual(response.status_code, 200)
