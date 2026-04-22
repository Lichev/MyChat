"""
test_delete_on_delivery.py

Verifies envelope lifetime:
1. Real-time path: envelope stored → forwarded → ACKed → deleted.
2. Offline/reconnect path: delete-on-FETCH (not delete-on-ACK for
   offline delivery via _deliver_pending_envelopes). This is the known
   Step 2 deviation from the blueprint ("Crash-before-ACK: re-delivered
   on reconnect"). The actual behaviour is: row deleted on fetch, not on
   explicit client ACK for the offline path.

Known deviation:
  services.fetch_and_delete_envelopes_for (line 266-305 of services.py)
  deletes rows inside the same SELECT FOR UPDATE → DELETE transaction.
  If the client crashes after delivery but before sending envelope.ack,
  the row is already gone — it is NOT re-delivered on reconnect.

  Blueprint §"Delete-on-delivery" states: "Crash-before-ACK: re-delivered
  on reconnect." This is contradicted by the implementation.
  This test documents actual behaviour; the deviation is flagged in the
  audit report as a known limitation.
"""

from django.test import TransactionTestCase
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.urls import re_path
from channels.routing import URLRouter
from asgiref.sync import sync_to_async

from PRIVATE_MESSAGES.consumers import PrivateMessageConsumer
from PRIVATE_MESSAGES.models import (
    EncryptedEnvelope, IdentityKey, SignedPreKey, OneTimePreKey
)
from PRIVATE_MESSAGES import services

UserModel = get_user_model()


def _make_user(username: str):
    return UserModel.objects.create_user(username=username, password="testpass123!")


def _make_friends(user_a, user_b):
    from FRIEND.models import Friend
    Friend.objects.get_or_create(from_user=user_a, to_user=user_b)
    Friend.objects.get_or_create(from_user=user_b, to_user=user_a)


def _make_identity(user):
    IdentityKey.objects.get_or_create(
        user=user,
        defaults={"ik_pub_curve25519": "A" * 44, "ik_pub_ed25519": "A" * 44},
    )
    SignedPreKey.objects.get_or_create(
        user=user,
        spk_id=1,
        defaults={"spk_pub": "A" * 44, "spk_sig": "B" * 88, "is_active": True},
    )


def _app():
    return URLRouter([
        re_path(r"^ws/pm/(?P<user_id>\d+)/$", PrivateMessageConsumer.as_asgi()),
    ])


async def _comm(user, peer_id):
    c = WebsocketCommunicator(_app(), f"/ws/pm/{peer_id}/")
    c.scope["user"] = user
    return c


class RealTimeDeleteOnDeliveryTest(TransactionTestCase):
    """
    Real-time path: A sends envelope → B receives envelope.deliver →
    B sends envelope.ack → envelope row is deleted immediately.
    """

    def setUp(self):
        self.user_a = _make_user("dod_a")
        self.user_b = _make_user("dod_b")
        _make_friends(self.user_a, self.user_b)
        _make_identity(self.user_a)
        _make_identity(self.user_b)

    async def test_envelope_deleted_after_ack(self):
        # Connect A (sender) to B's peer slot, and B (recipient) to A's slot
        comm_a = await _comm(self.user_a, self.user_b.pk)
        comm_b = await _comm(self.user_b, self.user_a.pk)

        connected_a, _ = await comm_a.connect()
        connected_b, _ = await comm_b.connect()
        self.assertTrue(connected_a)
        self.assertTrue(connected_b)

        try:
            # A sends an envelope
            await comm_a.send_json_to({
                "type":          "envelope.send",
                "ciphertext_b64": "CIPHERTEXT_FOR_DOD_TEST",
                "message_type":  1,
            })
            # A receives send.ack
            send_ack = await comm_a.receive_json_from()
            self.assertEqual(send_ack.get("type"), "envelope.send.ack",
                             f"A expected envelope.send.ack, got: {send_ack}")
            envelope_id = send_ack.get("envelope_id")
            self.assertIsNotNone(envelope_id, "envelope_id must be present in send.ack")

            # Row exists in DB
            exists_before_ack = await EncryptedEnvelope.objects.filter(
                pk=envelope_id
            ).aexists()
            self.assertTrue(exists_before_ack, "Envelope must exist before ACK")

            # B receives envelope.deliver
            deliver = await comm_b.receive_json_from()
            self.assertEqual(deliver.get("type"), "envelope.deliver",
                             f"B expected envelope.deliver, got: {deliver}")
            self.assertEqual(deliver.get("envelope_id"), envelope_id)

            # B sends envelope.ack
            await comm_b.send_json_to({"type": "envelope.ack", "envelope_id": envelope_id})
            ack_confirm = await comm_b.receive_json_from()
            self.assertEqual(ack_confirm.get("type"), "envelope.ack.confirm",
                             f"Expected ack.confirm, got: {ack_confirm}")
            self.assertTrue(ack_confirm.get("deleted"), "deleted must be True in ack.confirm")

            # Row deleted after ACK
            exists_after_ack = await EncryptedEnvelope.objects.filter(
                pk=envelope_id
            ).aexists()
            self.assertFalse(exists_after_ack,
                             "Envelope must be deleted immediately after ACK")
        finally:
            await comm_a.disconnect()
            await comm_b.disconnect()


class CrashBeforeAckOfflinePathTest(TransactionTestCase):
    """
    Offline path (delete-on-fetch): when B is offline, A's envelope is stored.
    When B reconnects, _deliver_pending_envelopes fetches AND deletes the rows
    atomically. If B crashes immediately after delivery but before sending
    envelope.ack, the row is already gone.

    This test documents that the row is deleted on reconnect-fetch,
    NOT re-delivered a second time. This is the known deviation from the
    blueprint.
    """

    def setUp(self):
        self.user_a = _make_user("crash_a")
        self.user_b = _make_user("crash_b")
        _make_friends(self.user_a, self.user_b)
        _make_identity(self.user_a)
        _make_identity(self.user_b)

    async def test_offline_envelope_stored_while_b_offline(self):
        """Store an envelope via service layer while B is offline. Row exists."""
        store = sync_to_async(services.store_envelope)
        envelope = await store(
            sender_id=self.user_a.pk,
            recipient_id=self.user_b.pk,
            ciphertext_b64="OFFLINE_ENVELOPE_001",
            message_type=1,
        )
        count = await EncryptedEnvelope.objects.filter(
            recipient=self.user_b
        ).acount()
        self.assertEqual(count, 1, "Envelope should be stored while B is offline")

    async def test_reconnect_delivers_and_deletes_on_fetch(self):
        """
        On B's reconnect, _deliver_pending_envelopes calls
        fetch_and_delete_envelopes_for which deletes on fetch.
        After reconnect the row is GONE — this is the documented
        delete-on-fetch deviation from the blueprint.
        """
        # Store envelope while B is offline
        store = sync_to_async(services.store_envelope)
        envelope = await store(
            sender_id=self.user_a.pk,
            recipient_id=self.user_b.pk,
            ciphertext_b64="OFFLINE_ENVELOPE_002",
            message_type=1,
        )

        # B reconnects — connect() triggers _deliver_pending_envelopes
        comm_b = await _comm(self.user_b, self.user_a.pk)
        connected, _ = await comm_b.connect()
        self.assertTrue(connected)
        try:
            # B should receive the pending envelope immediately on connect
            deliver = await comm_b.receive_json_from()
            self.assertEqual(deliver.get("type"), "envelope.deliver",
                             f"Expected envelope.deliver on reconnect, got: {deliver}")
            self.assertEqual(deliver.get("ciphertext_b64"), "OFFLINE_ENVELOPE_002")

            # *** KEY ASSERTION: row is already deleted at this point (delete-on-fetch) ***
            exists_after_delivery = await EncryptedEnvelope.objects.filter(
                pk=envelope.pk
            ).aexists()
            self.assertFalse(
                exists_after_delivery,
                "DOCUMENTED DEVIATION: fetch_and_delete_envelopes_for deletes on fetch "
                "(services.py lines 266-305). Row is gone BEFORE client sends ACK. "
                "If B crashes here, the message is lost (not re-delivered on next reconnect). "
                "Blueprint §'Delete-on-delivery' says crash-before-ACK should re-deliver — "
                "this implementation does NOT; it deletes on fetch. Flag as known limitation L1.",
            )
        finally:
            await comm_b.disconnect()

    async def test_no_redelivery_after_crash_before_ack(self):
        """
        If B crashes between receiving the delivered message and sending ACK,
        the row is already gone. A second reconnect does NOT re-deliver.
        This confirms the delete-on-fetch deviation.
        """
        store = sync_to_async(services.store_envelope)
        await store(
            sender_id=self.user_a.pk,
            recipient_id=self.user_b.pk,
            ciphertext_b64="OFFLINE_ENVELOPE_003",
            message_type=1,
        )

        # First connect — triggers fetch+delete
        comm_b1 = await _comm(self.user_b, self.user_a.pk)
        _, _ = await comm_b1.connect()
        await comm_b1.receive_json_from()  # consume the deliver event
        await comm_b1.disconnect()         # "crash" — no ACK sent

        # Second connect — no pending envelopes (row already deleted)
        comm_b2 = await _comm(self.user_b, self.user_a.pk)
        _, _ = await comm_b2.connect()
        try:
            # Should time out — no pending envelopes remain
            timed_out = await comm_b2.receive_nothing(timeout=0.5)
            self.assertTrue(
                timed_out,
                "No re-delivery on second reconnect (delete-on-fetch deviation confirmed). "
                "This is the documented L1 limitation.",
            )
        finally:
            await comm_b2.disconnect()
