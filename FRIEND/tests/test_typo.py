"""
L6 regression: verify that the self-friendship ValidationError message
contains "themselves" (not the old typo "themselfs").
"""

from django.core.exceptions import ValidationError
from django.test import TestCase

from FRIEND.models import Friend
from USERS.models import ChatUser


class SelfFriendshipTypoTest(TestCase):
    def setUp(self):
        self.user = ChatUser.objects.create_user(
            username='typotest',
            password='testpass123',
        )
        # Satisfy required fields via update to bypass full_clean at create time.
        ChatUser.objects.filter(pk=self.user.pk).update(
            first_name='Test',
            last_name='User',
            gender='male',
        )
        self.user.refresh_from_db()

    def test_self_friendship_error_message_says_themselves(self):
        """Friend.save() must raise ValidationError with 'themselves'."""
        friend = Friend(to_user=self.user, from_user=self.user)
        with self.assertRaises(ValidationError) as ctx:
            friend.save()
        message = str(ctx.exception)
        self.assertIn('themselves', message)
        self.assertNotIn('themselfs', message)
