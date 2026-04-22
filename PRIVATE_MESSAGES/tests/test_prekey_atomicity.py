"""
test_prekey_atomicity.py

H3: Verifies that prekey_bundle_for is @transaction.atomic so that a failure
during bundle assembly rolls back the OTPK consumption (not permanently burned).
"""

from unittest.mock import patch

from django.test import TransactionTestCase
from django.contrib.auth import get_user_model

from PRIVATE_MESSAGES.models import IdentityKey, OneTimePreKey, SignedPreKey
from PRIVATE_MESSAGES import services

UserModel = get_user_model()


def _make_user(username: str) -> UserModel:
    return UserModel.objects.create_user(username=username, password="testpass123!")


class PreKeyAtomicityTest(TransactionTestCase):
    """H3: OTPK must NOT be burned if prekey_bundle_for raises after consumption."""

    def setUp(self):
        self.user = _make_user("atomicity_user")
        IdentityKey.objects.create(
            user=self.user,
            ik_pub_curve25519="A" * 44,
            ik_pub_ed25519="B" * 44,
        )
        SignedPreKey.objects.create(
            user=self.user,
            spk_id=1,
            spk_pub="C" * 44,
            spk_sig="D" * 88,
            is_active=True,
        )
        OneTimePreKey.objects.create(
            user=self.user,
            otpk_id="key-001",
            otpk_pub="E" * 44,
        )

    def test_bundle_failure_rolls_back_otpk_consumption(self):
        """
        Monkeypatch SignedPreKey.objects.get to raise after consume_one_time_prekey
        would have been called, simulating a mid-assembly failure.

        Assert the OTPK row is still present in the DB after the exception.
        """
        # We patch IdentityKey.objects.get to succeed (returns the real object)
        # but patch SignedPreKey.objects.get to raise an unexpected error AFTER
        # the OTPK has been consumed. This simulates the scenario where the outer
        # transaction should protect the OTPK.
        original_spk_get = SignedPreKey.objects.get

        call_count = [0]

        def exploding_spk_get(**kwargs):
            call_count[0] += 1
            raise RuntimeError("Simulated mid-assembly failure")

        with patch.object(SignedPreKey.objects, 'get', side_effect=exploding_spk_get):
            with self.assertRaises(RuntimeError):
                services.prekey_bundle_for(self.user.pk)

        # The OTPK must still be present — the outer atomic rolled back the savepoint.
        still_exists = OneTimePreKey.objects.filter(
            user=self.user, otpk_id="key-001"
        ).exists()
        self.assertTrue(
            still_exists,
            "OTPK was permanently consumed even though bundle assembly failed. "
            "The @transaction.atomic decorator on prekey_bundle_for is missing or broken."
        )
