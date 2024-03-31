from django.contrib import admin

#
from .models import Friend, FriendshipRequest



@admin.register(Friend)
class FriendAdmin(admin.ModelAdmin):
    model = Friend
    raw_id_fields = ("to_user", "from_user")

@admin.register(FriendshipRequest)
class FriendshipRequestAdmin(admin.ModelAdmin):
    model = FriendshipRequest
    raw_id_fields = ("from_user", "to_user")
