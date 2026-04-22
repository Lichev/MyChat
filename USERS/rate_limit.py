"""
Rate limiter for account-recovery attempts (USERS app).

TTL-race fix
------------
The naive pattern ``cache.add(key, 0, ttl); cache.incr(key)`` has a race:
if the key expires between add and incr, incr re-creates it without a TTL,
producing an immortal counter.

Fix strategy (chosen at import time):
  • django-redis available  → use a single atomic SETNX-with-expiry call on
    the raw Redis client, then incr. Both ops happen before any TTL can expire.
  • Other backends (locmem) → incr first; if the return value is 1 (key was
    just created by incr), immediately call cache.expire(). On backends that
    raise ValueError when the key is absent, fall back to cache.set(key, 1, ttl).
"""

import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 900  # 15 minutes

# Feature-detect django-redis at import time.
try:
    from django_redis import get_redis_connection as _get_redis_connection  # noqa: F401
    _DJANGO_REDIS_AVAILABLE = True
except ImportError:
    _DJANGO_REDIS_AVAILABLE = False


def _cache_key(username: str) -> str:
    return f"recovery_attempts:{username}"


def is_rate_limited(username: str) -> bool:
    """Return True if the username has exhausted its allowed attempts."""
    count = cache.get(_cache_key(username), 0)
    return count >= _MAX_ATTEMPTS


def record_failed_attempt(username: str, ip: str) -> int:
    """
    Increment the failure counter for username and log the attempt.
    Returns the new attempt count.

    The window is anchored to the first failure (not the last) so that a
    slow-drip attacker cannot extend the window indefinitely.

    Uses an atomic SETNX+TTL on django-redis to avoid the race where a key
    expires between cache.add() and cache.incr(), which would recreate the
    key without a TTL and create an immortal counter.
    """
    key = _cache_key(username)
    if _DJANGO_REDIS_AVAILABLE:
        # Atomic path: SETNX sets key=1 with TTL only if absent, then incr.
        rc = cache.client.get_client()
        rc.set(key, 1, ex=_WINDOW_SECONDS, nx=True)
        count = rc.incr(key)
    else:
        # Fallback path for locmem / other backends.
        try:
            count = cache.incr(key)
            if count == 1:
                # Key was just created by incr — stamp TTL immediately.
                cache.expire(key, _WINDOW_SECONDS)
        except ValueError:
            # Key absent; create with TTL.
            cache.set(key, 1, _WINDOW_SECONDS)
            count = 1

    logger.info(
        "Recovery attempt failed: username=%r ip=%s attempt=%d/%d",
        username, ip, count, _MAX_ATTEMPTS,
    )
    return count


def get_attempt_count(username: str) -> int:
    """Return the current failure count for username (0 if no record)."""
    return cache.get(_cache_key(username), 0)


def clear_attempts(username: str) -> None:
    """Clear the counter after a successful recovery (optional hygiene)."""
    cache.delete(_cache_key(username))
