"""
test_csp_headers.py

Verifies that the Content-Security-Policy header served by Django:
  (a) IS emitted (django-csp 4.0 API is configured correctly).
  (b) Does NOT contain 'unsafe-inline' in the script-src directive.
  (c) DOES contain 'wasm-unsafe-eval' (required by Olm + libsodium WASM).
  (d) worker-src is 'self'.
  (e) frame-ancestors is 'none' (clickjacking defence).

Probes the live header via the Django test client, and also sanity-checks
the CONTENT_SECURITY_POLICY settings dict (django-csp 4.0 format).
"""

from django.test import TestCase, Client


class CSPHeaderTest(TestCase):
    """Inspect the Content-Security-Policy header on GET /."""

    def setUp(self):
        self.client = Client()

    def _get_csp_header(self, url: str = "/") -> str:
        response = self.client.get(url, HTTP_HOST="127.0.0.1")
        return response.get("Content-Security-Policy", "")

    @staticmethod
    def _extract_directive(csp: str, directive: str) -> str:
        """
        Extract the value of a single CSP directive from the header string.
        Returns an empty string if the directive is absent.
        """
        for part in csp.split(";"):
            part = part.strip()
            if part.lower().startswith(directive.lower() + " "):
                return part[len(directive):].strip()
            if part.lower() == directive.lower():
                return ""
        return ""

    def test_csp_header_is_emitted(self):
        csp = self._get_csp_header()
        self.assertTrue(
            csp,
            "Content-Security-Policy header must be emitted. If empty, "
            "django-csp is not reading settings correctly — verify the "
            "CONTENT_SECURITY_POLICY dict format (django-csp 4.0+).",
        )

    def test_script_src_has_no_unsafe_inline(self):
        csp = self._get_csp_header()
        script_src = self._extract_directive(csp, "script-src")
        self.assertNotIn(
            "'unsafe-inline'",
            script_src,
            f"script-src must not contain 'unsafe-inline'. Got: {script_src!r}",
        )

    def test_script_src_contains_wasm_unsafe_eval(self):
        csp = self._get_csp_header()
        script_src = self._extract_directive(csp, "script-src")
        self.assertIn(
            "'wasm-unsafe-eval'",
            script_src,
            f"script-src must include 'wasm-unsafe-eval' for Olm+libsodium. "
            f"Got: {script_src!r}",
        )

    def test_worker_src_is_self(self):
        csp = self._get_csp_header()
        worker_src = self._extract_directive(csp, "worker-src")
        self.assertIn(
            "'self'",
            worker_src,
            f"worker-src must include 'self'. Got: {worker_src!r}",
        )

    def test_frame_ancestors_is_none(self):
        csp = self._get_csp_header()
        fa = self._extract_directive(csp, "frame-ancestors")
        self.assertIn(
            "'none'",
            fa,
            f"frame-ancestors must be 'none' (clickjacking defence). "
            f"Got: {fa!r}",
        )

    def test_settings_use_django_csp_4_dict_format(self):
        """
        Belt-and-suspenders: verify settings are using the 4.x dict format,
        not the legacy CSP_SCRIPT_SRC tuple keys (which are silently ignored
        by django-csp 4.0+).
        """
        from django.conf import settings
        policy = getattr(settings, "CONTENT_SECURITY_POLICY", None)
        self.assertIsNotNone(
            policy,
            "CONTENT_SECURITY_POLICY dict must be defined (django-csp 4.0 format).",
        )
        directives = policy.get("DIRECTIVES", {})
        self.assertIn("script-src", directives)
        self.assertNotIn(
            "'unsafe-inline'",
            directives["script-src"],
            "CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src'] must not "
            "include 'unsafe-inline'.",
        )
        self.assertIn(
            "'wasm-unsafe-eval'",
            directives["script-src"],
            "CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src'] must "
            "include 'wasm-unsafe-eval'.",
        )
