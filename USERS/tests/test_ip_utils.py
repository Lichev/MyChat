"""
test_ip_utils.py

Verifies the trusted-proxy IP resolution logic in USERS.ip_utils (C7 fix).
"""

from django.test import TestCase, RequestFactory, override_settings

from USERS.ip_utils import get_client_ip


class XffWithoutTrustedProxyTest(TestCase):
    """XFF must be ignored when TRUSTED_PROXIES is empty (default)."""

    @override_settings(TRUSTED_PROXIES=[])
    def test_xff_rejected_without_trusted_proxy(self):
        """XFF header is present but TRUSTED_PROXIES is empty — REMOTE_ADDR wins."""
        factory = RequestFactory()
        request = factory.get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        request.META["HTTP_X_FORWARDED_FOR"] = "1.2.3.4"

        ip = get_client_ip(request)

        self.assertEqual(ip, "10.0.0.1",
                         "XFF must be ignored when the peer is not in TRUSTED_PROXIES")

    @override_settings(TRUSTED_PROXIES=[])
    def test_remote_addr_returned_without_xff(self):
        """No XFF present, empty TRUSTED_PROXIES — REMOTE_ADDR is returned as-is."""
        factory = RequestFactory()
        request = factory.get("/")
        request.META["REMOTE_ADDR"] = "203.0.113.5"
        request.META.pop("HTTP_X_FORWARDED_FOR", None)

        ip = get_client_ip(request)

        self.assertEqual(ip, "203.0.113.5")


class XffWithTrustedProxyTest(TestCase):
    """XFF must be honoured only when the direct peer is in TRUSTED_PROXIES."""

    @override_settings(TRUSTED_PROXIES=["10.0.0.1"])
    def test_xff_honoured_with_trusted_proxy(self):
        """When REMOTE_ADDR matches TRUSTED_PROXIES, the first XFF entry is returned."""
        factory = RequestFactory()
        request = factory.get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        request.META["HTTP_X_FORWARDED_FOR"] = "1.2.3.4, 10.0.0.2"

        ip = get_client_ip(request)

        self.assertEqual(ip, "1.2.3.4",
                         "First XFF entry must be used when peer is a trusted proxy")

    @override_settings(TRUSTED_PROXIES=["10.0.0.2"])
    def test_xff_ignored_when_peer_not_in_trusted_list(self):
        """REMOTE_ADDR is not in TRUSTED_PROXIES — XFF is ignored even though it is present."""
        factory = RequestFactory()
        request = factory.get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        request.META["HTTP_X_FORWARDED_FOR"] = "1.2.3.4"

        ip = get_client_ip(request)

        self.assertEqual(ip, "10.0.0.1")

    @override_settings(TRUSTED_PROXIES=["10.0.0.1"])
    def test_xff_trusted_proxy_no_xff_header(self):
        """Trusted proxy present but no XFF header — fall back to REMOTE_ADDR."""
        factory = RequestFactory()
        request = factory.get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        request.META.pop("HTTP_X_FORWARDED_FOR", None)

        ip = get_client_ip(request)

        self.assertEqual(ip, "10.0.0.1")
