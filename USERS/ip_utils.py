"""
ip_utils.py — safe client IP resolution.

By default returns request.META['REMOTE_ADDR'] (the TCP peer address).
HTTP_X_FORWARDED_FOR is only honoured when the direct peer (REMOTE_ADDR)
is listed in settings.TRUSTED_PROXIES, preventing header-injection attacks
that could bypass rate-limiting keyed on IP.

Configuration (MyChat/settings.py):
    TRUSTED_PROXIES = []           # default — XFF is never trusted
    TRUSTED_PROXIES = ['10.0.0.1'] # honour XFF only from this proxy IP
"""

from django.conf import settings


def get_client_ip(request) -> str:
    """Return the real client IP address for the given request.

    Reads REMOTE_ADDR unconditionally; promotes the first XFF entry only
    when REMOTE_ADDR appears in settings.TRUSTED_PROXIES.
    """
    remote_addr: str = request.META.get('REMOTE_ADDR', '')
    trusted: list = getattr(settings, 'TRUSTED_PROXIES', [])

    if remote_addr in trusted:
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()

    return remote_addr
