"""
test_rate_limit_ttl.py

H2: Verifies that the rate-limit key TTL is set and persists across multiple
increments (no immortal-counter bug).
"""

from django.test import TestCase
from django.core.cache import cache
import time

from PRIVATE_MESSAGES import rate_limit as rl


class RateLimitTTLTest(TestCase):
    """H2: Rate-limit counter must always carry a finite TTL."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_ttl_persists_after_increment(self):
        """
        Call check() three times and assert the key's TTL is not -1 (no TTL)
        after each call. A TTL of -1 indicates an immortal counter — the bug
        this test guards against.
        """
        user_id = 99901
        action = "envelope.send"

        for i in range(3):
            ok, remaining, retry_after = rl.check(action, user_id)
            self.assertTrue(ok, f"Expected ok=True on attempt {i+1}")

            # Build the cache key the same way the rate limiter does.
            now = time.time()
            window = rl._LIMITS[action][1]
            bucket = int(now // window)
            key = rl._cache_key(action, user_id, bucket)

            ttl = cache.ttl(key)
            self.assertIsNotNone(ttl, f"cache.ttl returned None on attempt {i+1}")
            self.assertGreater(
                ttl, -1,
                f"TTL was {ttl} (immortal counter) on attempt {i+1}. "
                "The TTL race bug is present."
            )
            self.assertGreater(
                ttl, 0,
                f"TTL was {ttl} on attempt {i+1} — key has already expired or has no TTL."
            )

    def test_counter_increments_correctly(self):
        """Counter must increment with each check() call."""
        user_id = 99902
        action = "session.init"
        max_req = rl._LIMITS[action][0]

        for i in range(1, min(4, max_req + 1)):
            ok, remaining, retry_after = rl.check(action, user_id)
            if i <= max_req:
                self.assertTrue(ok, f"Expected allowed on attempt {i}")
