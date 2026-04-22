"""
Log scrubber filter for PRIVATE_MESSAGES.

Recursively walks record.msg (if dict), record.args, and record.extra,
replacing values under any denylisted key with the literal "<scrubbed>".

Denylist combines the v1 set with v2 additions from blueprint § "Log scrubber"
and v2.1 additions from blueprint Addendum § "Log Scrubber Denylist Addition":
    password, token, secret, key, private_key, ciphertext, ciphertext_b64,
    ik_pub, ik_priv, spk_pub, spk_sig, otpk_pub, otpk_id,
    pickle_key, pickle, account_pickle, session_pickle,
    one_time_keys, one_time_key,
    master_key, key_b64

The filter MUST NOT crash on any log record; it always returns True so the
record continues to be handled (just with sensitive fields scrubbed).
"""

import logging
from typing import Any

_SCRUB_PLACEHOLDER = "<scrubbed>"

# All keys are lowercased for case-insensitive comparison.
_DENYLIST: frozenset[str] = frozenset(
    {
        # Generic secrets
        "password",
        "token",
        "secret",
        "key",
        "private_key",
        # Ciphertext fields
        "ciphertext",
        "ciphertext_b64",
        # Key material fields
        "ik_pub",
        "ik_priv",
        "spk_pub",
        "spk_sig",
        "otpk_pub",
        "otpk_id",
        # v2 additions (blueprint § "Log scrubber")
        "pickle_key",
        "pickle",
        "account_pickle",
        "session_pickle",
        "one_time_keys",
        "one_time_key",
        # v2.1 additions (blueprint Addendum § "Log Scrubber Denylist Addition")
        "master_key",
        "key_b64",
    }
)


def _scrub(obj: Any, depth: int = 0) -> Any:
    """
    Recursively scrub a dict, list, or tuple in place (returns a new object
    for immutable types). Depth is capped at 20 to guard against pathological
    nesting.
    """
    if depth > 20:
        return obj

    if isinstance(obj, dict):
        return {
            k: (_SCRUB_PLACEHOLDER if str(k).lower() in _DENYLIST else _scrub(v, depth + 1))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        scrubbed = [_scrub(item, depth + 1) for item in obj]
        return type(obj)(scrubbed)
    return obj


class PrivateChatLogScrubber(logging.Filter):
    """
    Logging filter that removes sensitive key material and ciphertext from
    log records before they reach any handler.

    Attach to both the root handler and the PRIVATE_MESSAGES logger in
    settings.LOGGING for belt-and-suspenders coverage.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            # Scrub record.msg if it is a dict (structured log).
            if isinstance(record.msg, dict):
                record.msg = _scrub(record.msg)

            # Scrub positional args tuple/list.
            if record.args:
                record.args = _scrub(record.args)

            # Scrub record.extra if present (some frameworks attach it).
            if hasattr(record, "extra") and isinstance(record.extra, dict):
                record.extra = _scrub(record.extra)

        except Exception:  # noqa: BLE001
            # Never crash the logging subsystem; just let the record through.
            pass

        return True
