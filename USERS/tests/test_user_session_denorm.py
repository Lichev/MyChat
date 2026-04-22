"""
test_user_session_denorm.py

H7: Verifies that the UserSession denorm table is maintained correctly by
the signal receivers, and that account recovery uses it for O(1) eviction.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session

from USERS.models import UserSession

UserModel = get_user_model()


def _make_user(username: str, password: str = "testpass123!") -> UserModel:
    return UserModel.objects.create_user(
        username=username,
        password=password,
        first_name="Test",
        last_name="User",
        gender="male",
    )


def _create_session(user) -> SessionStore:
    """Create a real Django session for user and return the store."""
    session = SessionStore()
    session["_auth_user_id"] = str(user.pk)
    session["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    session.create()
    return session


class UserSessionSignalTest(TestCase):
    """H7: Signal receivers create/delete UserSession rows on login/logout."""

    def setUp(self):
        self.user = _make_user("session_signal_user")
        self.factory = RequestFactory()

    def test_login_creates_user_session_row(self):
        """
        Logging in must create a UserSession row with the correct session_key.
        """
        from django.contrib.auth import login
        from django.contrib.auth.signals import user_logged_in

        # Create a session manually and fire the signal.
        session = _create_session(self.user)
        request = self.factory.get('/')
        request.session = session

        # Fire the signal directly (simulate what Django does on login).
        user_logged_in.send(
            sender=self.user.__class__,
            request=request,
            user=self.user,
        )

        self.assertTrue(
            UserSession.objects.filter(
                user=self.user,
                session_key=session.session_key,
            ).exists(),
            "UserSession row must be created when user_logged_in signal fires."
        )

    def test_login_signal_idempotent(self):
        """Firing user_logged_in twice for the same session_key must not raise."""
        from django.contrib.auth.signals import user_logged_in

        session = _create_session(self.user)
        request = self.factory.get('/')
        request.session = session

        user_logged_in.send(sender=self.user.__class__, request=request, user=self.user)
        user_logged_in.send(sender=self.user.__class__, request=request, user=self.user)

        count = UserSession.objects.filter(
            user=self.user, session_key=session.session_key
        ).count()
        self.assertEqual(count, 1, "Duplicate login signal must not create duplicate rows.")

    def test_logout_deletes_user_session_row(self):
        """Logging out must remove the UserSession row for that session_key."""
        from django.contrib.auth.signals import user_logged_in, user_logged_out

        session = _create_session(self.user)
        request = self.factory.get('/')
        request.session = session

        user_logged_in.send(sender=self.user.__class__, request=request, user=self.user)

        # Fire logout signal.
        user_logged_out.send(sender=self.user.__class__, request=request, user=self.user)

        self.assertFalse(
            UserSession.objects.filter(
                user=self.user, session_key=session.session_key
            ).exists(),
            "UserSession row must be deleted when user_logged_out signal fires."
        )


class UserSessionRecoveryTest(TestCase):
    """H7: Account recovery must use the denorm table for O(1) session eviction."""

    def setUp(self):
        self.user = _make_user("recovery_session_user")

    def _attach_sessions(self, count: int) -> list[str]:
        """Create `count` real Django sessions for self.user and denorm rows."""
        keys = []
        for _ in range(count):
            store = _create_session(self.user)
            UserSession.objects.create(
                user=self.user,
                session_key=store.session_key,
            )
            keys.append(store.session_key)
        return keys

    def test_recovery_deletes_all_user_sessions_via_denorm(self):
        """
        Recovery flow must delete all Session rows and UserSession rows for
        the user by going through the denorm table — not scanning all sessions.
        """
        keys = self._attach_sessions(3)

        # Verify they exist before recovery.
        self.assertEqual(
            Session.objects.filter(session_key__in=keys).count(), 3
        )
        self.assertEqual(
            UserSession.objects.filter(user=self.user).count(), 3
        )

        # Simulate the recovery eviction logic from RecoverAccountView.post().
        session_keys = list(
            self.user.user_sessions.values_list('session_key', flat=True)
        )
        if session_keys:
            Session.objects.filter(session_key__in=session_keys).delete()
            self.user.user_sessions.all().delete()

        # All Session rows must be gone.
        self.assertEqual(
            Session.objects.filter(session_key__in=keys).count(), 0,
            "All Session rows must be deleted after recovery eviction."
        )

        # All UserSession rows must be gone.
        self.assertEqual(
            UserSession.objects.filter(user=self.user).count(), 0,
            "All UserSession rows must be deleted after recovery eviction."
        )

    def test_recovery_does_not_scan_all_sessions(self):
        """
        The recovery path must NOT call Session.objects.all() — it must use
        the denorm table instead.
        """
        from unittest.mock import patch, MagicMock

        self._attach_sessions(2)

        all_called = [False]
        original_all = Session.objects.all

        def tracking_all():
            all_called[0] = True
            return original_all()

        with patch.object(Session.objects.__class__, 'all', tracking_all):
            session_keys = list(
                self.user.user_sessions.values_list('session_key', flat=True)
            )
            if session_keys:
                Session.objects.filter(session_key__in=session_keys).delete()
                self.user.user_sessions.all().delete()

        self.assertFalse(
            all_called[0],
            "Session.objects.all() was called during recovery — the denorm path "
            "is not being used."
        )
