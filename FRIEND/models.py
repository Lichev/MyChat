from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import models
from django.conf import settings
from django.utils import timezone
from FRIEND.exceptions import AlreadyExistsError, AlreadyFriendsError
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from FRIEND.signals import (
    friendship_request_accepted,
    friendship_request_rejected,
    friendship_request_canceled,
    friendship_request_viewed,
    friendship_removed
)

UserModel = get_user_model()

CACHE_TYPES = {
    "friends": "f-%s",
    "followers": "fo-%s",
    "following": "fl-%s",
    "blocks": "b-%s",
    "blocked": "bo-%s",
    "blocking": "bd-%s",
    "requests": "fr-%s",
    "sent_requests": "sfr-%s",
    "unread_requests": "fru-%s",
    "unread_request_count": "fruc-%s",
    "read_requests": "frr-%s",
    "rejected_requests": "frj-%s",
    "unrejected_requests": "frur-%s",
    "unrejected_request_count": "frurc-%s",
}

BUST_CACHES = {
    "friends": ["friends"],
    "followers": ["followers"],
    "blocks": ["blocks"],
    "blocked": ["blocked"],
    "following": ["following"],
    "blocking": ["blocking"],
    "requests": [
        "requests",
        "unread_requests",
        "unread_request_count",
        "read_requests",
        "rejected_requests",
        "unrejected_requests",
        "unrejected_request_count",
    ],
    "sent_requests": ["sent_requests"],
}


def cache_key(type, user_pk):
    """
    Build the cache key for a particular type of cached value
    """
    return CACHE_TYPES[type] % user_pk


def bust_cache(type, user_pk):
    """
    Bust our cache for a given type, can bust multiple caches
    """
    bust_keys = BUST_CACHES[type]
    keys = [CACHE_TYPES[k] % user_pk for k in bust_keys]
    cache.delete_many(keys)


class FriendshipRequest(models.Model):
    """ Model to represent a friendship requests """

    from_user = models.ForeignKey(
        UserModel,
        on_delete=models.CASCADE,
        related_name="friendship_request_sent"
    )

    to_user = models.ForeignKey(
        UserModel,
        on_delete=models.CASCADE,
        related_name="friendship_requests_sent"
    )

    message = models.TextField(_("Message"), blank=True)
    created = models.DateTimeField(default=timezone.now)
    rejected = models.DateTimeField(blank=True, null=True)
    viewed = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = _("Friendship Request")
        verbose_name_plural = _("Friendship Requests")
        unique_together = ("from_user", "to_user")

    def __str__(self):
        return f"User #{self.from_user_id} friendship requested #{self.to_user_id}"

    def accept(self):
        """ Accept friendship requests """
        Friend.objects.create(from_user=self.from_user, to_user=self.to_user)

        Friend.objects.create(from_user=self.to_user, to_user=self.from_user)

        friendship_request_accepted.send(sender=self, from_user=self.from_user, to_user=self.to_user)

        self.delete()

        FriendshipRequest.objects.filter(
            from_user=self.to_user,
            to_user=self.from_user
        ).delete()

        # Bust requests cache - request is deleted
        bust_cache("requests", self.to_user.pk)
        bust_cache("sent_requests", self.from_user.pk)
        # Bust reverse requests cache - reverse request might be deleted
        bust_cache("requests", self.from_user.pk)
        bust_cache("sent_requests", self.to_user.pk)
        # Bust friends cache - new friends added
        bust_cache("friends", self.to_user.pk)
        bust_cache("friends", self.from_user.pk)
        return True

    def reject(self):
        """ reject friendship requests """
        self.rejected = timezone.now()
        self.save()
        friendship_request_rejected.send(sender=self)
        bust_cache("requests", self.to_user.pk)
        bust_cache("sent_requests", self.from_user.pk)
        return True

    def cancel(self):
        """ cancel friendship requests """
        friendship_request_canceled.send(sender=self)
        self.delete()
        bust_cache("requests", self.to_user.pk)
        bust_cache("sent_requests", self.from_user.pk)
        return True

    def mark_viewed(self):
        self.viewed = timezone.now()
        friendship_request_viewed.send(sender=self)
        self.save()
        bust_cache("requests", self.to_user.pk)
        return True


class FriendShipManager(models.Manager):
    """ friendship manager """

    def friends(self, user):
        """ return list of all friends """
        key = cache_key("friends", user.pk)
        friends = cache.get(key)

        if friends is None:
            qs = Friend.objects.select_related("from_user").filter(to_user=user)
            friends = [u.from_user for u in qs]
            cache.set(key, friends)

        return friends

    def requests(self, user):
        """ return list of friendship requests """
        key = cache_key("requests", user.pk)
        requests = cache.get(key)

        if requests is None:
            qs = FriendshipRequest.objects.filter(to_user=user)
            qs = self._friendship_request_select_related(qs, 'from_user', 'to_user')
            requests = list(qs)
            cache.set(key, requests)

        return requests

    def sent_requests(self, user):
        """ return list of sent friendship requests """
        key = cache_key("sent_requests", user.pk)
        requests = cache.get(key)

        if requests is not None:
            qs = FriendshipRequest.objects.filter(from_user=user)
            qs = self._friendship_request_select_related(qs, 'from_user', 'to_user')
            requests = list(qs)
            cache.set(key, requests)

        return requests

    def add_friend(self, from_user, to_user, message=None):
        if from_user == to_user:
            raise ValidationError("Users cannot be friends with themselves")

        if self.are_friends(from_user, to_user):
            raise ValidationError("Users already friends")

        if FriendshipRequest.objects.filter(from_user=from_user, to_user=to_user).exists():
            raise ValidationError("You already have requested friendship with this user")

        if FriendshipRequest.objects.filter(from_user=to_user, to_user=from_user).exists():
            raise ValidationError("This user already requested friendship from you.")

        if message is not None:
            message = ""

        request, created = FriendshipRequest.objects.get_or_create(from_user=from_user, to_user=to_user)

        if created is False:
            raise AlreadyExistsError("Friendship already requested")

        if message:
            request.message = message
            request.save()

        bust_cache("requests", to_user.pk)
        bust_cache("sent_requests", from_user.pk)
        return request

    def remove_friend(self, from_user, to_user):
        """Destroy a friendship relationship"""
        try:
            qs = Friend.objects.filter(
                to_user__in=[to_user, from_user], from_user__in=[from_user, to_user]
            )

            if qs:
                friendship_removed.send(
                    sender=qs[0], from_user=from_user, to_user=to_user
                )
                qs.delete()
                bust_cache("friends", to_user.pk)
                bust_cache("friends", from_user.pk)
                return True
            else:
                return False
        except Friend.DoesNotExist:
            return False

    def are_friends(self, user1, user2):
        """ Check if two users are friends """
        friends1 = cache.get(cache_key("friends", user1.pk))
        friends2 = cache.get(cache_key("friends", user2.pk))

        if friends1 and user2 in friends1:
            return True
        elif friends2 and user1 in friends2:
            return True
        else:
            try:
                Friend.objects.get(to_user=user1, from_user=user2)
                return True
            except Friend.DoesNotExist:
                return False

    def _friendship_request_select_related(self, qs, *fields):
        strategy = getattr(
            settings,
            "FRIENDSHIP_MANAGER_FRIENDSHIP_REQUEST_SELECT_RELATED_STRATEGY",
            "select_related",
        )
        if strategy == "select_related":
            qs = qs.select_related(*fields)
        elif strategy == "prefetch_related":
            qs = qs.prefetch_related(*fields)
        return qs


class Friend(models.Model):
    """ Model to represent FriendShip """
    to_user = models.ForeignKey(
        UserModel,
        models.CASCADE,
        related_name="friends"
    )

    from_user = models.ForeignKey(
        UserModel,
        models.CASCADE,
        related_name='_unused_friend_relation'
    )

    created = models.DateTimeField(default=timezone.now)
    objects = FriendShipManager()

    class Meta:
        verbose_name = _("Friend")
        verbose_name_plural = _("Friends")
        unique_together = ("from_user", "to_user")

    def __str__(self):
        return f"User #{self.to_user_id} is friend with #{self.from_user_id}"

    def save(self, *args, **kwargs):
        # Ensure users can't be friends with themself
        if self.to_user == self.from_user:
            raise ValidationError('Users cannot be friends with themselfs')
        super().save(*args, **kwargs)
