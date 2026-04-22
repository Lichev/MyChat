"""
L4 regression: ChatUser.get_profile_picture_filename must return only the
bare filename (e.g. 'foo.png'), not the full path prefix.  Also must return
'' when no profile picture is set.
"""

from unittest.mock import PropertyMock, patch

from django.test import TestCase

from USERS.models import ChatUser


def _make_user(username):
    u = ChatUser.objects.create_user(username=username, password='pass123')
    ChatUser.objects.filter(pk=u.pk).update(
        first_name='Test', last_name='User', gender='male'
    )
    u.refresh_from_db()
    return u


class ProfileFilenameTest(TestCase):
    def setUp(self):
        self.user = _make_user('pictest')

    def test_returns_bare_filename(self):
        """Should return only the last path component, not the full prefix."""
        # Simulate a stored path via the ImageField's .name attribute.
        with patch.object(
            type(self.user).profile_picture,
            'name',
            new_callable=lambda: property(lambda self_inner: f'profile_images/{self_inner.pk}/foo.png'),
        ):
            # We patch .name on the field descriptor — simpler to assign directly
            # via the field's internal name attribute.
            pass

        # Simpler approach: set name directly on the FieldFile instance.
        self.user.profile_picture.name = f'profile_images/{self.user.pk}/foo.png'
        result = self.user.get_profile_picture_filename()
        self.assertEqual(result, 'foo.png')

    def test_empty_returns_empty_string(self):
        """When profile_picture is falsy (empty), should return ''."""
        self.user.profile_picture.name = ''
        # Empty FieldFile evaluates to falsy via __bool__
        result = self.user.get_profile_picture_filename()
        self.assertEqual(result, '')

    def test_nested_path_returns_only_filename(self):
        """Deep paths like 'a/b/c/d.jpg' should yield 'd.jpg'."""
        self.user.profile_picture.name = 'a/b/c/d.jpg'
        result = self.user.get_profile_picture_filename()
        self.assertEqual(result, 'd.jpg')
