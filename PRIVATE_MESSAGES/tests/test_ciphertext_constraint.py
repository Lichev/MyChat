"""
L5 regression: DB-level CheckConstraint on EncryptedEnvelope.ciphertext_b64.

The constraint pm_envelope_ciphertext_len_bound must reject any row whose
ciphertext_b64 exceeds 65536 characters. Defence-in-depth already exists in
the WebSocket consumer (consumers.py:278), but this guards every future
write path.
"""

from datetime import timedelta

from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from USERS.models import ChatUser
from PRIVATE_MESSAGES.models import EncryptedEnvelope


def _make_user(username):
    u = ChatUser.objects.create_user(username=username, password='testpass123')
    ChatUser.objects.filter(pk=u.pk).update(
        first_name='Test', last_name='User', gender='male'
    )
    u.refresh_from_db()
    return u


class CiphertextLengthConstraintTest(TestCase):
    def setUp(self):
        self.sender = _make_user('sender_ct')
        self.recipient = _make_user('recipient_ct')

    def _envelope_kwargs(self, ciphertext):
        return dict(
            sender=self.sender,
            recipient=self.recipient,
            ciphertext_b64=ciphertext,
            message_type=EncryptedEnvelope.MESSAGE_TYPE_REGULAR,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def test_max_length_accepted(self):
        """65536-character ciphertext must be accepted."""
        EncryptedEnvelope.objects.create(**self._envelope_kwargs('A' * 65536))

    def test_over_length_rejected(self):
        """65537-character ciphertext must raise IntegrityError."""
        with self.assertRaises(IntegrityError):
            EncryptedEnvelope.objects.create(**self._envelope_kwargs('A' * 65537))
