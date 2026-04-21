import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 900  # 15 minutes


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
    The TTL is set on first write; subsequent increments reuse the existing
    expiry so the window is anchored to the first failure, not the last.
    """
    key = _cache_key(username)
    # cache.add only sets the key if it does not yet exist, establishing the TTL.
    cache.add(key, 0, _WINDOW_SECONDS)
    try:
        count = cache.incr(key)
    except ValueError:
        # Key disappeared between add and incr (edge case under high concurrency).
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
