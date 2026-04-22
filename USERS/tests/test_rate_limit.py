"""
test_rate_limit.py

H2: Verifies that USERS/rate_limit.py record_failed_attempt sets a TTL on the
counter key and that the TTL persists across multiple increments (no immortal
counter bug).
"""

from django.test import TestCase
from django.core.cache import cache

from USERS import rate_limit as rl


class RecoveryRateLimitTTLTest(TestCase):
    """H2: Recovery rate-limit counter must always carry a finite TTL."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_ttl_persists_after_increment(self):
        """
        Call record_failed_attempt three times for the same username and assert
        that the cache key carries a finite TTL after each call.

        A TTL of -1 indicates an immortal counter (the bug this test guards against).
        """
        username = "ttl_test_user"
        ip = "127.0.0.1"

        for i in range(1, 4):
            count = rl.record_failed_attempt(username, ip)
            self.assertEqual(count, i, f"Expected count={i}, got {count}")

            key = rl._cache_key(username)
            ttl = cache.ttl(key)

            self.assertIsNotNone(ttl, f"cache.ttl returned None on attempt {i}")
            self.assertGreater(
                ttl, -1,
                f"TTL was {ttl} (immortal counter) on attempt {i}. "
                "The TTL race bug is present in USERS/rate_limit.py."
            )
            self.assertGreater(
                ttl, 0,
                f"TTL was {ttl} on attempt {i} — key has expired or has no TTL."
            )

    def test_is_rate_limited_after_max_attempts(self):
        """Exceeding _MAX_ATTEMPTS must cause is_rate_limited to return True."""
        username = "rate_limited_user"
        ip = "127.0.0.1"

        for _ in range(rl._MAX_ATTEMPTS):
            rl.record_failed_attempt(username, ip)

        self.assertTrue(
            rl.is_rate_limited(username),
            f"Expected is_rate_limited=True after {rl._MAX_ATTEMPTS} attempts."
        )

    def test_clear_attempts_removes_key(self):
        """clear_attempts must remove the counter key entirely."""
        username = "clearable_user"
        rl.record_failed_attempt(username, "127.0.0.1")
        rl.clear_attempts(username)

        self.assertEqual(
            rl.get_attempt_count(username), 0,
            "Attempt count must be 0 after clear_attempts()."
        )
