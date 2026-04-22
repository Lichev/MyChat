"""
Signal receivers for the USERS app.

H7: Maintain the UserSession denorm table by hooking into Django's
built-in user_logged_in and user_logged_out signals.

These receivers keep UserSession in sync with Django's session store so
that account-recovery session invalidation can use an O(1) FK-based DELETE
rather than a full-table scan of django_session.
"""

import logging

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def create_user_session(sender, request, user, **kwargs):
    """
    Create a UserSession row when a user logs in.

    Uses get_or_create so that a session_key that somehow already has a
    row (e.g. reused key after a server restart) is handled idempotently.
    If the key exists but belongs to a DIFFERENT user (should never happen
    in practice — Django regenerates session keys on login), we delete the
    stale row first to avoid a unique-constraint violation.
    """
    from .models import UserSession

    session_key = getattr(request.session, 'session_key', None)
    if not session_key:
        logger.warning(
            "user_logged_in: no session_key on request.session for user_id=%s",
            user.pk,
        )
        return

    # Idempotent upsert: delete any prior row with this session_key (covers
    # the edge case where the key was reused), then create a fresh row.
    UserSession.objects.filter(session_key=session_key).delete()
    UserSession.objects.create(user=user, session_key=session_key)

    logger.debug(
        "user_session.created: user_id=%s session_key=%s…",
        user.pk,
        session_key[:8],
    )


@receiver(user_logged_out)
def delete_user_session(sender, request, user, **kwargs):
    """
    Delete the UserSession row when a user explicitly logs out.

    user may be None if the session was anonymous (Django sends the signal
    even for anonymous logouts), so we guard for that.
    """
    from .models import UserSession

    if user is None:
        return

    session_key = getattr(request.session, 'session_key', None)
    if not session_key:
        return

    deleted_count, _ = UserSession.objects.filter(session_key=session_key).delete()
    if deleted_count:
        logger.debug(
            "user_session.deleted: user_id=%s session_key=%s…",
            user.pk,
            session_key[:8],
        )
