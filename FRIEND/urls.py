from django.urls import path, include
from FRIEND.views import friendship_add_friend, friendship_accept, friendship_reject, friendship_cancel, \
    remove_friend_view, show_friends_view, show_friends_request

urlpatterns = [
    path("add/<slug:to_username>/", friendship_add_friend, name='friendship_add_friend'),
    path("accept/<str:friendship_request_id>/", friendship_accept, name='friendship_accept'),
    path("reject/<str:friendship_request_id>/", friendship_reject, name='friendship_reject'),
    path("cancel/<str:friendship_request_id>/", friendship_cancel, name='friendship_cancel'),
    path("remove/<int:friend_id>/", remove_friend_view, name='remove_friend'),
    path("my-list/", show_friends_view, name='show_friends'),
    path('friend-requests/', show_friends_request, name='show_friends_request')

]
