"""
test_can_delete.py

Verifies Message.can_delete() correctness and that the admin-check path
does NOT materialise the full admins queryset (M3).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from CHAT_ROOMS.models import Message, PublicChatRoom

UserModel = get_user_model()


def _make_user(username: str) -> UserModel:
    return UserModel.objects.create_user(
        username=username,
        password="TestPass123!",
        first_name="Test",
        last_name="User",
    )


class CanDeleteTest(TestCase):

    def setUp(self):
        self.creator = _make_user("creator_cd")
        self.admin = _make_user("admin_cd")
        self.sender = _make_user("sender_cd")
        self.stranger = _make_user("stranger_cd")

        self.room = PublicChatRoom.objects.create(
            name="can-delete-test-room",
            creator=self.creator,
        )
        self.room.admins.add(self.admin)

        self.message = Message.objects.create(
            room=self.room,
            sender=self.sender,
            content="hello",
        )

    def test_sender_can_delete_own_message(self):
        self.assertTrue(self.message.can_delete(self.sender))

    def test_creator_can_delete_any_message(self):
        self.assertTrue(self.message.can_delete(self.creator))

    def test_admin_can_delete_message(self):
        self.assertTrue(self.message.can_delete(self.admin))

    def test_non_participant_cannot_delete(self):
        self.assertFalse(self.message.can_delete(self.stranger))

    def test_admin_check_uses_exists_not_all(self):
        """
        Verify the admin-check path issues at most 1 query — confirming
        .filter(pk=…).exists() is used instead of materialising admins.all().

        We isolate the admin path by using a non-sender, non-creator user
        who IS an admin, and assert the query count is bounded.
        """
        # Fetch the message fresh (room and sender already cached from setUp),
        # then time only the can_delete call itself.
        msg = Message.objects.select_related('room', 'sender').get(pk=self.message.pk)

        with self.assertNumQueries(1):
            # The single query allowed is the admins.filter(pk=…).exists() check.
            # sender == admin? No. creator == admin? No. → one DB hit for .exists().
            result = msg.can_delete(self.admin)

        self.assertTrue(result)

    def test_non_participant_check_uses_exists_not_all(self):
        """
        Non-participant also triggers the .exists() path (returns False).
        Should still be at most 1 query.
        """
        msg = Message.objects.select_related('room', 'sender').get(pk=self.message.pk)

        with self.assertNumQueries(1):
            result = msg.can_delete(self.stranger)

        self.assertFalse(result)
