from django.urls import path
from CHAT_ROOMS.views import (
    PublicChatRoomMessages, PublicChatRoomCreateView, PublicChatRoomEditView,
    add_member_to_room, remove_member_from_room, search_chat_rooms,
)

urlpatterns = [
    path('<int:room_id>/', PublicChatRoomMessages.as_view(), name='public_chat_messages'),
    path('create/', PublicChatRoomCreateView.as_view(), name='create_room'),
    path('<int:room_id>/edit/', PublicChatRoomEditView.as_view(), name='edit_room'),
    path('<int:room_id>/members/add/<str:username>/', add_member_to_room, name='add_member_to_room'),
    path('<int:room_id>/members/remove/<str:username>/', remove_member_from_room, name='remove_member_from_room'),
    path('search/<str:query>/', search_chat_rooms, name='search_chat_rooms'),
]
