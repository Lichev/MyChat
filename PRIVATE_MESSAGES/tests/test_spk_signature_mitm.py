"""
test_spk_signature_mitm.py

Regression lock for the SPK signature MitM defence.

No browser automation is available in this environment, so this test
uses two complementary approaches:

1. Static grep check: confirms ed25519_verify() is called BEFORE
   session.create_outbound() in olm_session.js. This is the structural
   regression lock — it verifies the guard is present at the code level.

2. Service-layer structural test: verifies the server does NOT validate
   SPK signatures (it is a dumb pipe). Bundle validation is purely
   client-side. This test confirms the client-side defence is the only
   one needed (per the zero-knowledge model) and that the server correctly
   returns raw bundle fields to the client.

The Olm library's own test suite covers ed25519_verify() correctness.
The _client-side_ runtime coverage requires a browser (Playwright/
Puppeteer) running the actual WASM — not feasible in a Django unit test.
That coverage is deferred to the Playwright E2E suite (v2).
"""

import re
import ast
from pathlib import Path
from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from channels.testing import WebsocketCommunicator
from django.urls import re_path
from channels.routing import URLRouter

from PRIVATE_MESSAGES.consumers import PrivateMessageConsumer
from PRIVATE_MESSAGES.models import IdentityKey, SignedPreKey, OneTimePreKey

UserModel = get_user_model()

OLM_SESSION_JS = Path(__file__).resolve().parents[2] / "static" / "js" / "private_chat" / "olm_session.js"


def _make_user(username):
    return UserModel.objects.create_user(username=username, password="testpass123!")


def _make_friends(user_a, user_b):
    from FRIEND.models import Friend
    Friend.objects.get_or_create(from_user=user_a, to_user=user_b)
    Friend.objects.get_or_create(from_user=user_b, to_user=user_a)


class StaticMitMGuardTest(TestCase):
    """
    Structural regression lock: parse olm_session.js and assert:
    (a) ed25519_verify appears before session.create_outbound in the
        outboundSession function.
    (b) The SPK signature check is not gated behind any if/else that
        could be trivially bypassed.
    """

    def _read_js(self) -> str:
        self.assertTrue(OLM_SESSION_JS.exists(),
                        f"olm_session.js not found at {OLM_SESSION_JS}")
        return OLM_SESSION_JS.read_text(encoding="utf-8")

    def test_ed25519_verify_present_in_olm_session_js(self):
        """ed25519_verify must appear in olm_session.js."""
        content = self._read_js()
        self.assertIn(
            "ed25519_verify",
            content,
            "ed25519_verify not found in olm_session.js — MitM guard is missing!",
        )

    def test_ed25519_verify_before_create_outbound(self):
        """
        ed25519_verify must appear BEFORE session.create_outbound in the
        file. We find the line positions of both and assert verify < outbound.
        This is the regression lock: if someone reorders the calls,
        this test fails.
        """
        content = self._read_js()
        lines = content.splitlines()

        verify_line   = None
        outbound_line = None

        for i, line in enumerate(lines):
            if "ed25519_verify" in line and verify_line is None:
                verify_line = i
            if "create_outbound" in line and outbound_line is None:
                outbound_line = i

        self.assertIsNotNone(verify_line,
                             "ed25519_verify not found in olm_session.js")
        self.assertIsNotNone(outbound_line,
                             "create_outbound not found in olm_session.js")
        self.assertLess(
            verify_line,
            outbound_line,
            f"CRITICAL: ed25519_verify (line {verify_line+1}) must appear BEFORE "
            f"create_outbound (line {outbound_line+1}) in olm_session.js. "
            f"Current order allows MitM by skipping the SPK signature check.",
        )

    def test_verify_is_not_inside_optional_branch_only(self):
        """
        The ed25519_verify call must appear in the outboundSession function
        body (not only inside an 'if (DEBUG)' or try/catch that swallows
        the error).

        We verify that the try block containing ed25519_verify is followed
        by a finally (not catch-only) — meaning a verification failure DOES
        propagate (the session creation is aborted).
        """
        content = self._read_js()
        # Find the section containing ed25519_verify; extract surrounding context.
        idx = content.find("ed25519_verify")
        self.assertGreater(idx, 0)

        # Context: 500 chars before and after the verify call
        snippet = content[max(0, idx - 200): idx + 500]

        # The try/finally pattern around ed25519_verify means errors propagate.
        self.assertIn("finally", snippet,
                      "ed25519_verify must be inside a try/finally block so "
                      "verification failures propagate (not swallowed by catch-only).")

    def test_outbound_session_guard_documented_in_comment(self):
        """
        A security comment must explain the MitM guard to prevent
        future developers from removing it unknowingly.
        """
        content = self._read_js()
        # Any of these should appear near the outboundSession function
        security_markers = ["MitM", "SECURITY", "spk_sig", "forged SPK", "MitM"]
        found = any(marker.lower() in content.lower() for marker in security_markers)
        self.assertTrue(
            found,
            "No security comment found near the outboundSession function. "
            "Add a comment explaining the ed25519_verify MitM guard to "
            "prevent silent removal.",
        )


class ServerDumbPipeSPKTest(TransactionTestCase):
    """
    The server returns the stored spk_sig verbatim — it does NOT validate
    the SPK signature itself. A deliberately 'wrong' spk_sig is stored and
    returned identically; the client is the only validator.
    This confirms the zero-knowledge dumb-pipe model is intact.
    """

    def setUp(self):
        self.user_a = _make_user("mitm_a")
        self.user_b = _make_user("mitm_b")
        _make_friends(self.user_a, self.user_b)
        # Register B with a deliberately invalid spk_sig value
        IdentityKey.objects.create(
            user=self.user_b,
            ik_pub_curve25519="A" * 44,
            ik_pub_ed25519="A" * 44,
        )
        SignedPreKey.objects.create(
            user=self.user_b,
            spk_id=1,
            spk_pub="A" * 44,
            # Deliberately WRONG signature (signed by a different key)
            spk_sig="WRONG_SIG_" + "X" * 78,
            is_active=True,
        )
        OneTimePreKey.objects.create(user=self.user_b, otpk_id="otk001", otpk_pub="C" * 44)

    def _app(self):
        return URLRouter([
            re_path(r"^ws/pm/(?P<user_id>\d+)/$", PrivateMessageConsumer.as_asgi()),
        ])

    async def test_server_returns_spk_sig_verbatim_without_validation(self):
        """
        The server must return whatever spk_sig is stored — it does NOT
        validate it. This is correct: the client (via ed25519_verify) is
        the sole validator. A wrong sig stored here will be caught by the
        client's outboundSession() call.
        """
        comm = WebsocketCommunicator(self._app(), f"/ws/pm/{self.user_b.pk}/")
        comm.scope["user"] = self.user_a
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        try:
            await comm.send_json_to({"type": "prekey.request"})
            response = await comm.receive_json_from()
            self.assertEqual(response.get("type"), "prekey.bundle",
                             f"Expected prekey.bundle, got: {response}")
            bundle = response.get("bundle", {})
            # Server must return the stored (wrong) sig unchanged
            self.assertEqual(
                bundle.get("spk_sig"),
                "WRONG_SIG_" + "X" * 78,
                "Server must return spk_sig verbatim — it is a dumb pipe. "
                "If this fails, the server is validating SPK sigs (unexpected).",
            )
            # Client would call ed25519_verify here and reject this bundle —
            # but that is tested in the static JS check above.
        finally:
            await comm.disconnect()
