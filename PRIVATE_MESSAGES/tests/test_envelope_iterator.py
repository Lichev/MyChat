"""
test_envelope_iterator.py

H4: Verifies that fetch_and_delete_envelopes_for uses an iterator and does NOT
materialise all rows into a Python list at once.
"""

from unittest.mock import patch, call

from django.test import TransactionTestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from PRIVATE_MESSAGES.models import EncryptedEnvelope
from PRIVATE_MESSAGES import services

UserModel = get_user_model()

_CHUNK = services._ENVELOPE_FETCH_CHUNK
_DELETE_BATCH = services._ENVELOPE_DELETE_BATCH


def _make_user(username: str) -> UserModel:
    return UserModel.objects.create_user(username=username, password="testpass123!")


def _seed_envelopes(sender, recipient, count: int):
    expires = timezone.now() + timedelta(days=7)
    EncryptedEnvelope.objects.bulk_create([
        EncryptedEnvelope(
            sender=sender,
            recipient=recipient,
            ciphertext_b64="A" * 64,
            message_type=1,
            expires_at=expires,
        )
        for _ in range(count)
    ])


class EnvelopeIteratorTest(TransactionTestCase):
    """H4: fetch_and_delete_envelopes_for must stream via iterator, not list()."""

    def setUp(self):
        self.sender = _make_user("iter_sender")
        self.recipient = _make_user("iter_recipient")

    def test_iterator_chunks_do_not_materialise_all_rows(self):
        """
        Seed N=300 envelopes. Call fetch_and_delete_envelopes_for.
        Assert that:
        1. All 300 envelopes are returned in results.
        2. The queryset was iterated (not list()'d) — verified by confirming
           that the QuerySet.iterator method was called.
        3. All envelopes are deleted from the DB afterward.
        """
        N = 300
        _seed_envelopes(self.sender, self.recipient, N)

        from django.db.models.query import QuerySet
        original_iterator = QuerySet.iterator
        iterator_called = [False]

        def tracking_iterator(self_qs, chunk_size=None):
            iterator_called[0] = True
            return original_iterator(self_qs, chunk_size=chunk_size)

        with patch.object(QuerySet, 'iterator', tracking_iterator):
            results = services.fetch_and_delete_envelopes_for(self.recipient.pk)

        self.assertEqual(len(results), N,
                         f"Expected {N} envelopes returned, got {len(results)}")

        self.assertTrue(
            iterator_called[0],
            "QuerySet.iterator() was NOT called — the implementation is materialising "
            "all rows with list() instead of streaming."
        )

        remaining = EncryptedEnvelope.objects.filter(recipient=self.recipient).count()
        self.assertEqual(remaining, 0, "All envelopes should have been deleted.")

    def test_delete_batching_respects_batch_size(self):
        """
        Seed N > _ENVELOPE_DELETE_BATCH envelopes. Verify that delete is called
        in batches of at most _ENVELOPE_DELETE_BATCH IDs.
        """
        # This test is meaningful only when N > _DELETE_BATCH.
        # Default _DELETE_BATCH is 500; seed 600 to trigger two delete calls.
        N = _DELETE_BATCH + 100
        _seed_envelopes(self.sender, self.recipient, N)

        original_delete = EncryptedEnvelope.objects.filter(
            recipient=self.recipient
        ).delete  # just a reference

        delete_id_counts = []

        original_filter = EncryptedEnvelope.objects.filter

        def tracking_filter(**kwargs):
            qs = original_filter(**kwargs)
            if 'pk__in' in kwargs:
                delete_id_counts.append(len(kwargs['pk__in']))
            return qs

        with patch.object(EncryptedEnvelope.objects.__class__, 'filter', tracking_filter):
            results = services.fetch_and_delete_envelopes_for(self.recipient.pk)

        self.assertEqual(len(results), N)
        # Each batch should be at most _DELETE_BATCH.
        for count in delete_id_counts:
            self.assertLessEqual(
                count, _DELETE_BATCH,
                f"A delete batch of {count} exceeds the limit of {_DELETE_BATCH}."
            )
