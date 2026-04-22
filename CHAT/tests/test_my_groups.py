"""
test_my_groups.py

Verifies that chat_info_json includes groups for users who are members or
admins of a room, not only the creator.  Covers M1 from the remediation plan.
"""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase, Client

from CHAT_ROOMS.models import PublicChatRoom

UserModel = get_user_model()


def _make_user(username: str) -> UserModel:
    return UserModel.objects.create_user(
        username=username,
        password="TestPass123!",
        first_name="Test",
        last_name="User",
    )


def _make_room(creator, name: str) -> PublicChatRoom:
    return PublicChatRoom.objects.create(name=name, creator=creator)


class ChatInfoJsonMyGroupsTest(TestCase):
    """
    chat_info_json should include rooms where the requesting user is a
    member, admin, or creator — not just creator.
    """

    def setUp(self):
        self.creator = _make_user("creator_user")
        self.admin_user = _make_user("admin_user")
        self.member_user = _make_user("member_user")
        self.outsider = _make_user("outsider_user")

        self.room = _make_room(self.creator, "Test Room M1")
        self.room.admins.add(self.admin_user)
        self.room.members.add(self.member_user)

    def _get_groups_ids(self, user):
        client = Client()
        client.force_login(user)
        response = client.get('/chat/info/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        return {g['id'] for g in data['groups_data']}

    def test_creator_sees_own_room(self):
        ids = self._get_groups_ids(self.creator)
        self.assertIn(self.room.id, ids)

    def test_admin_sees_administered_room(self):
        """Admin (not creator) must appear in groups_data after M1 fix."""
        ids = self._get_groups_ids(self.admin_user)
        self.assertIn(self.room.id, ids)

    def test_member_sees_joined_room(self):
        """Plain member must appear in groups_data after M1 fix."""
        ids = self._get_groups_ids(self.member_user)
        self.assertIn(self.room.id, ids)

    def test_outsider_does_not_see_room(self):
        """A user with no relationship to the room must not see it."""
        ids = self._get_groups_ids(self.outsider)
        self.assertNotIn(self.room.id, ids)

    def test_no_duplicates_for_creator_who_is_also_admin(self):
        """
        If the creator is also explicitly listed as an admin, .distinct()
        must prevent the room from appearing twice.
        """
        self.room.admins.add(self.creator)
        ids_list = self._get_groups_ids_list(self.creator)
        self.assertEqual(
            ids_list.count(self.room.id),
            1,
            "Room appeared more than once — .distinct() is missing.",
        )

    def _get_groups_ids_list(self, user):
        client = Client()
        client.force_login(user)
        response = client.get('/chat/info/')
        data = json.loads(response.content)
        return [g['id'] for g in data['groups_data']]
