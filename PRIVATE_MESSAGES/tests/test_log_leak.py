"""
test_log_leak.py

Verifies that PrivateChatLogScrubber prevents sensitive fields from
reaching any log handler output, and validates the scrubber unit-level
behaviour with a synthetic LogRecord.
"""

import logging
import io

from django.test import TestCase

from PRIVATE_MESSAGES.logging_filters import PrivateChatLogScrubber, _scrub


# ── Helpers ──────────────────────────────────────────────────────────────────

def _capture_logger(name: str) -> tuple[logging.Logger, io.StringIO]:
    """Attach a fresh StringIO StreamHandler to *name* logger; return both."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    # Attach the scrubber as a filter on the handler itself (mirrors settings.py).
    handler.addFilter(PrivateChatLogScrubber())
    lg = logging.getLogger(name)
    lg.addHandler(handler)
    lg.setLevel(logging.DEBUG)
    return lg, buf


def _remove_handler(lg: logging.Logger, buf: io.StringIO):
    for h in list(lg.handlers):
        if hasattr(h, "stream") and h.stream is buf:
            lg.removeHandler(h)
            h.close()


# ── Unit test: scrubber ───────────────────────────────────────────────────────

class ScrubberUnitTest(TestCase):
    """
    Build a LogRecord whose args contain a dict with sensitive values and
    verify all three are replaced with '<scrubbed>'.
    """

    def test_scrubs_top_level_sensitive_keys(self):
        sensitive_args = {
            "ciphertext_b64": "MYSECRET",
            "pickle_key":     "XYZ",
            "nested": {
                "otpk_pub": "ABC"
            },
        }
        scrubbed = _scrub(sensitive_args)
        self.assertEqual(scrubbed["ciphertext_b64"], "<scrubbed>",
                         "ciphertext_b64 should be scrubbed at top level")
        self.assertEqual(scrubbed["pickle_key"], "<scrubbed>",
                         "pickle_key should be scrubbed at top level")
        self.assertEqual(scrubbed["nested"]["otpk_pub"], "<scrubbed>",
                         "otpk_pub should be scrubbed at second level (nested dict)")

    def test_non_sensitive_keys_pass_through(self):
        safe = {"user_id": 42, "action": "test", "count": 7}
        scrubbed = _scrub(safe)
        self.assertEqual(scrubbed["user_id"], 42)
        self.assertEqual(scrubbed["action"], "test")
        self.assertEqual(scrubbed["count"], 7)

    def test_scrubber_filter_on_log_record(self):
        """
        PrivateChatLogScrubber.filter() must return True (record passes)
        but sanitise args that contain sensitive keys.
        """
        scrubber = PrivateChatLogScrubber()
        record = logging.LogRecord(
            name="PRIVATE_MESSAGES",
            level=logging.DEBUG,
            pathname="test",
            lineno=0,
            msg="pm.test: user_id=%s data=%s",
            args=("user_42", {"ciphertext_b64": "MYSECRET", "pickle_key": "XYZ",
                               "nested": {"otpk_pub": "ABC"}}),
            exc_info=None,
        )
        result = scrubber.filter(record)
        self.assertTrue(result, "Filter must always return True")
        # args is a tuple; second element is the dict
        data_arg = record.args[1]
        self.assertEqual(data_arg["ciphertext_b64"], "<scrubbed>")
        self.assertEqual(data_arg["pickle_key"], "<scrubbed>")
        self.assertEqual(data_arg["nested"]["otpk_pub"], "<scrubbed>")

    def test_scrubber_never_crashes_on_bizarre_record(self):
        """PrivateChatLogScrubber must not raise under any circumstances."""
        scrubber = PrivateChatLogScrubber()
        record = logging.LogRecord(
            name="PRIVATE_MESSAGES",
            level=logging.WARNING,
            pathname="test",
            lineno=0,
            msg=None,          # None msg
            args=None,
            exc_info=None,
        )
        result = scrubber.filter(record)
        self.assertTrue(result)

    def test_scrubber_handles_deeply_nested_dict(self):
        """Depth cap at 20 should not error; values beyond cap pass through."""
        obj = {}
        inner = obj
        for _ in range(25):
            inner["x"] = {}
            inner = inner["x"]
        inner["ciphertext_b64"] = "DEEPSECRET"
        # Should not raise; deep value may pass through (depth > 20)
        result = _scrub(obj)
        self.assertIsNotNone(result)

    def test_all_denylist_keys_are_scrubbed(self):
        """Every key in the denylist should be scrubbed."""
        from PRIVATE_MESSAGES.logging_filters import _DENYLIST
        data = {k: f"value_of_{k}" for k in _DENYLIST}
        scrubbed = _scrub(data)
        for k in _DENYLIST:
            self.assertEqual(scrubbed[k], "<scrubbed>",
                             f"Key '{k}' should be scrubbed but was not")


# ── Integration test: log output ─────────────────────────────────────────────

class LogOutputLeakTest(TestCase):
    """
    Exercise the consumer-level loggers (PRIVATE_MESSAGES and root) at
    DEBUG level and assert that ciphertext / key material never reaches
    the handler stream output.
    """

    # Markers that must never appear in captured log text
    _CIPHERTEXT_MARKER = "CIPHERTEXT_B64_CANARY_VALUE_XQ9"
    _OTPK_MARKER       = "OTPK_PUB_CANARY_VALUE_YR8"
    _SPK_SIG_MARKER    = "SPK_SIG_CANARY_VALUE_ZT7"
    _PICKLE_KEY_MARKER = "PICKLE_KEY_CANARY_VALUE_WV6"

    def setUp(self):
        self.pm_logger, self.pm_buf = _capture_logger("PRIVATE_MESSAGES")
        self.root_logger, self.root_buf = _capture_logger("root_pm_test")

    def tearDown(self):
        _remove_handler(self.pm_logger, self.pm_buf)
        _remove_handler(self.root_logger, self.root_buf)

    def _fire_synthetic_workload(self, lg: logging.Logger):
        """
        Emit log records covering every pattern the consumer/services emit,
        some intentionally containing sensitive key names to prove the
        scrubber intercepts them.
        """
        # Normal informational logs (no sensitive content)
        lg.info("pm.connected: user_id=%s peer_id=%s channel=%s", 1, 2, "test.ch")
        lg.info("pm.identity_registered: user_id=%s ik_curve_len=%d ik_ed_len=%d", 1, 44, 44)
        lg.info("pm.otpk_published: user_id=%s count=%d", 1, 100)

        # Logs that CARRY sensitive dict args — scrubber must strip them
        lg.debug("pm.synthetic_sensitive: data=%s",
                 {"ciphertext_b64": self._CIPHERTEXT_MARKER,
                  "otpk_pub":       self._OTPK_MARKER,
                  "spk_sig":        self._SPK_SIG_MARKER,
                  "pickle_key":     self._PICKLE_KEY_MARKER})

        lg.warning("pm.prekey_bundle_debug: bundle=%s",
                   {"ik_pub_ed25519": "someIKpub",
                    "spk_sig":        self._SPK_SIG_MARKER,
                    "otpk_pub":       self._OTPK_MARKER})

    def _assert_no_leak(self, buf: io.StringIO, label: str):
        output = buf.getvalue()
        for marker, name in [
            (self._CIPHERTEXT_MARKER, "ciphertext_b64"),
            (self._OTPK_MARKER,       "otpk_pub"),
            (self._SPK_SIG_MARKER,    "spk_sig"),
            (self._PICKLE_KEY_MARKER, "pickle_key"),
        ]:
            self.assertNotIn(
                marker,
                output,
                msg=(
                    f"[{label}] Sensitive value for '{name}' leaked into log output. "
                    f"PrivateChatLogScrubber failed to intercept it."
                ),
            )

    def test_pm_logger_does_not_leak_sensitive_values(self):
        self._fire_synthetic_workload(self.pm_logger)
        self._assert_no_leak(self.pm_buf, "PRIVATE_MESSAGES logger")

    def test_root_handler_path_does_not_leak_sensitive_values(self):
        self._fire_synthetic_workload(self.root_logger)
        self._assert_no_leak(self.root_buf, "root logger")

    def test_services_log_does_not_expose_ciphertext_length(self):
        """
        The services.py logger emits ciphertext_len (an int), not the
        ciphertext itself. Confirm a realistic services log pattern is clean.
        """
        lg = self.pm_logger
        # Mirrors services.store_envelope log call exactly
        lg.info(
            "pm.envelope_stored: envelope_id=%s sender_id=%s recipient_id=%s "
            "message_type=%d ciphertext_len=%d",
            "uuid-here", 1, 2, 0, 128,
        )
        output = self.pm_buf.getvalue()
        # ciphertext_len is fine; ciphertext itself must never appear
        self.assertNotIn(self._CIPHERTEXT_MARKER, output)
        self.assertIn("ciphertext_len=128", output,
                      "ciphertext_len should appear (it's metadata, not the value)")
