"""
L1 regression: add_member_to_room and remove_member_from_room must not issue
an extra UPDATE on the room row after the M2M add/remove.

We measure queries with django.test.utils.CaptureQueriesContext and assert
that no UPDATE targeting the rooms table appears — the M2M operation alone
should consist of one INSERT (add) or one DELETE (remove) without a trailing
UPDATE on the parent row.
"""

from django.test import TestCase, RequestFactory
from django.test.utils import CaptureQueriesContext
from django.db import connection

from CHAT_ROOMS.views import add_member_to_room, remove_member_from_room
from CHAT_ROOMS.models import PublicChatRoom
from USERS.models import ChatUser


def _make_user(username):
    u = ChatUser.objects.create_user(username=username, password='pass123')
    ChatUser.objects.filter(pk=u.pk).update(
        first_name='Test', last_name='User', gender='male'
    )
    u.refresh_from_db()
    return u


class MemberMutationQueryTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin = _make_user('admin_mm')
        self.member = _make_user('member_mm')
        self.room = PublicChatRoom.objects.create(
            name='TestRoomMM',
            creator=self.admin,
        )

    def _post(self, view, user, room_id, username):
        request = self.factory.post(f'/rooms/{room_id}/{username}/')
        request.user = user
        return view(request, room_id=room_id, username=username)

    def test_add_member_issues_no_room_update(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self._post(add_member_to_room, self.admin, self.room.pk, self.member.username)
        self.assertEqual(response.status_code, 200)
        room_updates = [
            q['sql'] for q in ctx.captured_queries
            if 'UPDATE' in q['sql'].upper()
            and 'chat_rooms_publicchatroom' in q['sql'].lower()
        ]
        self.assertEqual(
            room_updates, [],
            msg=f"Unexpected UPDATE on rooms table after add: {room_updates}",
        )

    def test_remove_member_issues_no_room_update(self):
        self.room.members.add(self.member)
        with CaptureQueriesContext(connection) as ctx:
            response = self._post(remove_member_from_room, self.admin, self.room.pk, self.member.username)
        self.assertEqual(response.status_code, 200)
        room_updates = [
            q['sql'] for q in ctx.captured_queries
            if 'UPDATE' in q['sql'].upper()
            and 'chat_rooms_publicchatroom' in q['sql'].lower()
        ]
        self.assertEqual(
            room_updates, [],
            msg=f"Unexpected UPDATE on rooms table after remove: {room_updates}",
        )
