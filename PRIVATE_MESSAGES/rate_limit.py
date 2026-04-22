"""
Redis-backed sliding-window rate limiter for PRIVATE_MESSAGES.

Uses a fixed-window approximation (bucket = floor(now / window_seconds)).
Falls back to Django's locmem cache when Redis is not configured so unit
tests work without a live Redis instance.

Cache key format (from blueprint):
    pm:rl:<action>:<user_id>:<window_bucket>

Returns
-------
check(action, user_id) -> tuple[bool, int, int]
    ok          – True if the action is allowed (counter incremented)
    remaining   – requests remaining in this window (0 when denied)
    retry_after – seconds until the window resets (0 when ok)
"""

import logging
import math
import time

from django.core.cache import cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-action configuration: (max_requests, window_seconds)
# All limits are from blueprint § "Rate limits".
# ---------------------------------------------------------------------------
_LIMITS: dict[str, tuple[int, int]] = {
    "prekey.request":     (30,  10 * 60),   # 30 / 10 min
    "envelope.send":      (60,  60),         # 60 / 1 min
    "prekey.publish":     (3,   10 * 60),    # 3 / 10 min
    "key.rotate":         (1,   6 * 60 * 60),# 1 / 6 h
    "session.init":       (20,  60),         # 20 / 1 min
    "identity.fingerprint":(60, 10 * 60),   # 60 / 10 min
}

_CACHE_KEY_PREFIX = "pm:rl"


def _cache_key(action: str, user_id: int, bucket: int) -> str:
    return f"{_CACHE_KEY_PREFIX}:{action}:{user_id}:{bucket}"


def check(action: str, user_id: int) -> tuple[bool, int, int]:
    """
    Check and increment the rate-limit counter for (action, user_id).

    Returns (ok, remaining, retry_after).
    - If the action is not in _LIMITS, it is allowed unconditionally.
    - On any cache error, the request is allowed (fail-open) and the error
      is logged at WARNING level so we don't silently degrade but also don't
      DOS ourselves if the cache layer blips.
    """
    if action not in _LIMITS:
        logger.debug("pm_ratelimit: unknown action %r — allowing", action)
        return True, 0, 0

    max_requests, window_seconds = _LIMITS[action]
    now = time.time()
    bucket = int(now // window_seconds)
    key = _cache_key(action, user_id, bucket)

    # Window expires at the end of the current bucket.
    bucket_end = (bucket + 1) * window_seconds
    ttl = math.ceil(bucket_end - now)

    try:
        # cache.add sets the key only if absent, establishing the TTL.
        cache.add(key, 0, ttl)
        count = cache.incr(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "pm_ratelimit: cache error for action=%r user_id=%s — failing open: %s",
            action,
            user_id,
            exc,
        )
        return True, max_requests, 0

    if count > max_requests:
        # Already over limit — decrement to avoid unbounded counter growth,
        # then report exhaustion.
        try:
            cache.decr(key)
        except Exception:  # noqa: BLE001
            pass
        retry_after = ttl
        logger.info(
            "pm_ratelimit: DENIED action=%r user_id=%s count=%d max=%d retry_after=%ds",
            action,
            user_id,
            count,
            max_requests,
            retry_after,
        )
        return False, 0, retry_after

    remaining = max(0, max_requests - count)
    return True, remaining, 0
