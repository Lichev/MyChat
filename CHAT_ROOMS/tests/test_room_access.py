"""
test_room_access.py

Verifies that the room-access gate correctly blocks and admits users based on
is_private, for_friends_only, and membership/creator/admin status.

Covers C1, C2, C3, and C4 from the remediation plan.
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

from CHAT_ROOMS.models import PublicChatRoom
from CHAT_ROOMS.services import can_user_access_room, get_public_chat_rooms

UserModel = get_user_model()


def _make_user(username: str) -> UserModel:
    return UserModel.objects.create_user(username=username, password="testpass123!")


def _make_friends(user_a, user_b):
    from FRIEND.models import Friend
    Friend.objects.get_or_create(from_user=user_a, to_user=user_b)
    Friend.objects.get_or_create(from_user=user_b, to_user=user_a)


def _make_room(creator, name: str = "test-room", is_private: bool = False, for_friends_only: bool = False):
    return PublicChatRoom.objects.create(
        name=name,
        creator=creator,
        is_private=is_private,
        for_friends_only=for_friends_only,
    )


class PrivateRoomAccessTest(TestCase):
    """C1: non-members must be blocked from private rooms."""

    def setUp(self):
        self.creator = _make_user("creator")
        self.outsider = _make_user("outsider")
        self.member = _make_user("member")
        self.admin = _make_user("admin_user")
        self.private_room = _make_room(self.creator, name="private-room", is_private=True)
        self.private_room.members.add(self.member)
        self.private_room.admins.add(self.admin)

    def test_private_room_blocks_non_member(self):
        """Non-member GET of private room returns 404, not leaking existence."""
        self.client.force_login(self.outsider)
        response = self.client.get(f"/chat/rooms/{self.private_room.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_private_room_allows_creator(self):
        self.assertTrue(can_user_access_room(self.creator, self.private_room))

    def test_private_room_allows_member(self):
        self.assertTrue(can_user_access_room(self.member, self.private_room))

    def test_private_room_allows_admin(self):
        self.assertTrue(can_user_access_room(self.admin, self.private_room))

    def test_private_room_denies_outsider(self):
        self.assertFalse(can_user_access_room(self.outsider, self.private_room))


class ForFriendsOnlyRoomTest(TestCase):
    """C4: for_friends_only gate must actually be enforced."""

    def setUp(self):
        self.creator = _make_user("ffo_creator")
        self.friend = _make_user("ffo_friend")
        self.stranger = _make_user("ffo_stranger")
        self.ffo_room = _make_room(self.creator, name="friends-room", for_friends_only=True)
        _make_friends(self.creator, self.friend)

    def test_for_friends_only_honours_friendship_friend_allowed(self):
        """A friend of the creator may access a for_friends_only room."""
        self.assertTrue(can_user_access_room(self.friend, self.ffo_room))

    def test_for_friends_only_honours_friendship_non_friend_blocked(self):
        """A non-friend may not access a for_friends_only room."""
        self.assertFalse(can_user_access_room(self.stranger, self.ffo_room))

    def test_for_friends_only_view_non_friend_returns_404(self):
        """HTTP GET by non-friend returns 404 (no existence leak)."""
        self.client.force_login(self.stranger)
        response = self.client.get(f"/chat/rooms/{self.ffo_room.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_for_friends_only_view_friend_returns_200(self):
        """HTTP GET by friend returns 200."""
        self.client.force_login(self.friend)
        response = self.client.get(f"/chat/rooms/{self.ffo_room.pk}/")
        self.assertEqual(response.status_code, 200)


class SearchHidesPrivateRoomsTest(TestCase):
    """C2: search endpoints must exclude private rooms the user cannot access."""

    def setUp(self):
        self.creator = _make_user("search_creator")
        self.outsider = _make_user("search_outsider")
        self.member = _make_user("search_member")
        self.public_room = _make_room(self.creator, name="visible-public-room")
        self.private_room = _make_room(self.creator, name="hidden-private-room", is_private=True)
        self.private_room.members.add(self.member)

    def test_search_hides_private_rooms_for_outsider(self):
        """search_chat_rooms must not return private rooms to non-members."""
        self.client.force_login(self.outsider)
        response = self.client.get("/chat/rooms/search/hidden-private-room/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        room_names = [r["name"] for r in data]
        self.assertNotIn("hidden-private-room", room_names)

    def test_search_shows_private_room_to_member(self):
        """search_chat_rooms must return private rooms to members."""
        self.client.force_login(self.member)
        response = self.client.get("/chat/rooms/search/hidden-private-room/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        room_names = [r["name"] for r in data]
        self.assertIn("hidden-private-room", room_names)

    def test_build_search_data_hides_private_rooms(self):
        """_build_search_data (CHAT unified search) also excludes inaccessible private rooms."""
        self.client.force_login(self.outsider)
        response = self.client.get("/chat/search/", {"q": "hidden-private-room"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        room_names = [r["name"] for r in data["rooms"]]
        self.assertNotIn("hidden-private-room", room_names)


class SidebarExcludesPrivateRoomsTest(TestCase):
    """C3: get_public_chat_rooms(user) must not surface private rooms to outsiders."""

    def setUp(self):
        self.creator = _make_user("sidebar_creator")
        self.outsider = _make_user("sidebar_outsider")
        self.member = _make_user("sidebar_member")
        self.public_room = _make_room(self.creator, name="sidebar-public-room")
        self.private_room = _make_room(self.creator, name="sidebar-private-room", is_private=True)
        self.private_room.members.add(self.member)

    def test_sidebar_context_excludes_private_rooms_for_outsiders(self):
        """get_public_chat_rooms(outsider) must not contain the private room."""
        qs = get_public_chat_rooms(self.outsider)
        room_ids = list(qs.values_list("id", flat=True))
        self.assertNotIn(self.private_room.pk, room_ids)

    def test_sidebar_context_includes_private_rooms_for_members(self):
        """get_public_chat_rooms(member) must include private rooms the member belongs to."""
        qs = get_public_chat_rooms(self.member)
        room_ids = list(qs.values_list("id", flat=True))
        self.assertIn(self.private_room.pk, room_ids)

    def test_sidebar_context_includes_public_rooms_for_all(self):
        """get_public_chat_rooms returns public rooms to any authenticated user."""
        qs = get_public_chat_rooms(self.outsider)
        room_ids = list(qs.values_list("id", flat=True))
        self.assertIn(self.public_room.pk, room_ids)
