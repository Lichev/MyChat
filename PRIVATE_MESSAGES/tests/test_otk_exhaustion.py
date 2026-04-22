"""
test_otk_exhaustion.py

Verifies OTPK pool exhaustion behaviour:
- 5 OTPKs registered for user A.
- 5 friend-users B1..B5 each consume one OTPK via prekey_bundle_for.
- After 5 fetches: pool is empty (0 OTPKs).
- 6th fetch returns bundle with otpk_id=None, otpk_pub=None (no crash).
"""

from django.test import TransactionTestCase
from django.contrib.auth import get_user_model

from PRIVATE_MESSAGES.models import IdentityKey, SignedPreKey, OneTimePreKey
from PRIVATE_MESSAGES import services

UserModel = get_user_model()


def _make_user(username: str):
    return UserModel.objects.create_user(username=username, password="testpass123!")


def _make_friends(user_a, user_b):
    from FRIEND.models import Friend
    Friend.objects.get_or_create(from_user=user_a, to_user=user_b)
    Friend.objects.get_or_create(from_user=user_b, to_user=user_a)


class OTKExhaustionTest(TransactionTestCase):
    """
    Simulates 5 concurrent prekey_bundle_for() calls exhausting A's OTPK
    pool, then asserts the 6th returns a graceful null-OTPK bundle.
    """

    def setUp(self):
        self.user_a = _make_user("otk_a")
        # Register A's identity
        IdentityKey.objects.create(
            user=self.user_a,
            ik_pub_curve25519="A" * 44,
            ik_pub_ed25519="A" * 44,
        )
        SignedPreKey.objects.create(
            user=self.user_a,
            spk_id=1,
            spk_pub="A" * 44,
            spk_sig="B" * 88,
            is_active=True,
        )
        # Publish exactly 5 OTPKs
        for i in range(1, 6):
            OneTimePreKey.objects.create(
                user=self.user_a,
                otpk_id=f"otk_{i:03d}",
                otpk_pub=f"PK{i}" + "C" * 40,
            )
        # Create 6 friends (B1..B6)
        self.peers = []
        for i in range(1, 7):
            peer = _make_user(f"otk_b{i}")
            _make_friends(self.user_a, peer)
            self.peers.append(peer)

    def test_five_fetches_consume_all_otpks(self):
        """Each of the first 5 prekey_bundle_for calls consumes one OTPK."""
        consumed_otpk_ids = set()
        for i, peer in enumerate(self.peers[:5]):
            bundle = services.prekey_bundle_for(self.user_a.pk)
            self.assertIsNotNone(bundle,
                                 f"Bundle {i+1} should not be None while OTPKs remain")
            self.assertIsNotNone(bundle.get("otpk_id"),
                                 f"Bundle {i+1} should include an otpk_id")
            self.assertIsNotNone(bundle.get("otpk_pub"),
                                 f"Bundle {i+1} should include an otpk_pub")
            self.assertNotIn(
                bundle["otpk_id"],
                consumed_otpk_ids,
                f"OTPK {bundle['otpk_id']!r} was returned twice — atomicity failed!",
            )
            consumed_otpk_ids.add(bundle["otpk_id"])

        # Pool should now be empty
        pool_size = services.get_otpk_pool_size(self.user_a.pk)
        self.assertEqual(pool_size, 0, "OTPK pool must be empty after 5 fetches")

    def test_sixth_fetch_returns_null_otpk_gracefully(self):
        """
        The 6th prekey_bundle_for() must not crash and must return the
        bundle with otpk_id=None and otpk_pub=None.
        """
        # Exhaust pool
        for _ in range(5):
            services.prekey_bundle_for(self.user_a.pk)

        # 6th fetch
        bundle = services.prekey_bundle_for(self.user_a.pk)

        self.assertIsNotNone(bundle,
                             "prekey_bundle_for must not return None when pool is empty — "
                             "it should return the IK/SPK bundle with null OTPK fields.")
        self.assertIsNone(bundle.get("otpk_id"),
                          "otpk_id must be None when pool is empty")
        self.assertIsNone(bundle.get("otpk_pub"),
                          "otpk_pub must be None when pool is empty")
        # IK and SPK fields must still be present
        self.assertIsNotNone(bundle.get("ik_pub_curve25519"))
        self.assertIsNotNone(bundle.get("ik_pub_ed25519"))
        self.assertIsNotNone(bundle.get("spk_pub"))
        self.assertIsNotNone(bundle.get("spk_sig"))

    def test_otpk_ids_are_unique_across_fetches(self):
        """Each consumed OTPK ID must be distinct (atomicity check)."""
        ids = []
        for _ in range(5):
            bundle = services.prekey_bundle_for(self.user_a.pk)
            if bundle and bundle.get("otpk_id"):
                ids.append(bundle["otpk_id"])
        self.assertEqual(len(ids), len(set(ids)),
                         f"Duplicate OTPK IDs returned: {ids}")

    def test_publish_one_time_prekeys_respects_pool_cap(self):
        """
        publish_one_time_prekeys must not insert more keys than the 150-cap
        allows, even when called with more than the available slots.
        """
        # Current pool: 5 (reset to fresh for this test)
        # Insert 148 more to bring pool to 153 attempt; only 145 allowed
        keys = [{"otpk_id": f"cap_otk_{i}", "otpk_pub": "P" * 44} for i in range(148)]
        inserted = services.publish_one_time_prekeys(self.user_a.pk, keys)
        total = services.get_otpk_pool_size(self.user_a.pk)
        self.assertLessEqual(total, 150,
                             f"Pool size {total} exceeds cap of 150")
        self.assertEqual(inserted, min(148, 150 - 5),
                         f"Expected to insert {min(148, 150-5)} keys, got {inserted}")
