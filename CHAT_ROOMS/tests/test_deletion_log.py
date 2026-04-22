"""
test_deletion_log.py

H5: Verifies that MessageDeletionLog rows survive when the associated Message
is deleted, and that snapshot fields are populated correctly.
"""

from django.test import TestCase
from django.contrib.auth import get_user_model

from CHAT_ROOMS.models import PublicChatRoom, Message, MessageDeletionLog

UserModel = get_user_model()


def _make_user(username: str) -> UserModel:
    return UserModel.objects.create_user(username=username, password="testpass123!")


class MessageDeletionLogTest(TestCase):
    """H5: Audit log must survive message deletion and retain snapshot fields."""

    def setUp(self):
        self.creator = _make_user("log_creator")
        self.deleter = _make_user("log_deleter")
        self.room = PublicChatRoom.objects.create(
            name="log_test_room",
            creator=self.creator,
        )
        self.message = Message.objects.create(
            room=self.room,
            sender=self.creator,
            content="Hello world",
        )

    def _create_log(self):
        """Helper: create a MessageDeletionLog with all snapshot fields."""
        return MessageDeletionLog.objects.create(
            message=self.message,
            deleter=self.deleter,
            message_id_snapshot=self.message.pk,
            message_sender_snapshot=self.message.sender,
            message_room_snapshot=self.message.room,
        )

    def test_deletion_log_survives_message_delete(self):
        """Deleting the Message must NOT cascade-delete the MessageDeletionLog."""
        log = self._create_log()
        log_pk = log.pk

        self.message.delete()

        # Log row must still exist.
        self.assertTrue(
            MessageDeletionLog.objects.filter(pk=log_pk).exists(),
            "MessageDeletionLog was cascade-deleted when the Message was deleted. "
            "The on_delete=SET_NULL fix is not in place."
        )

    def test_snapshot_fields_populated_after_message_delete(self):
        """Snapshot fields must retain values after the message row is gone."""
        log = self._create_log()
        log_pk = log.pk
        original_message_id = self.message.pk
        original_sender_id = self.creator.pk
        original_room_id = self.room.pk

        self.message.delete()

        log_reloaded = MessageDeletionLog.objects.get(pk=log_pk)

        # The FK is now NULL.
        self.assertIsNone(
            log_reloaded.message_id,
            "message FK should be NULL after message deletion."
        )

        # Snapshot fields must retain their original values.
        self.assertEqual(
            log_reloaded.message_id_snapshot, original_message_id,
            "message_id_snapshot must not change after message deletion."
        )
        self.assertEqual(
            log_reloaded.message_sender_snapshot_id, original_sender_id,
            "message_sender_snapshot must retain the original sender."
        )
        self.assertEqual(
            log_reloaded.message_room_snapshot_id, original_room_id,
            "message_room_snapshot must retain the original room."
        )

    def test_str_uses_snapshot_id(self):
        """__str__ must use message_id_snapshot (works after message deletion)."""
        log = self._create_log()
        self.message.delete()

        log_reloaded = MessageDeletionLog.objects.get(pk=log.pk)
        expected = f"{self.deleter.username} deleted message {log_reloaded.message_id_snapshot}"
        self.assertEqual(str(log_reloaded), expected)
