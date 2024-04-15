from django.urls import path, include
from CHAT_ROOMS.views import PublicChatRoomView, PublicChatRoomMessages, PublicChatRoomCreateView, \
    PublicChatRoomEditView, add_member_to_room, remove_member_from_room, search_chat_rooms

urlpatterns = (
    path('', PublicChatRoomView.as_view(), name='public_chat_room'),
    path('<int:room_id>/', PublicChatRoomMessages.as_view(), name='public_chat_messages'),
    path('create_room/', PublicChatRoomCreateView.as_view(), name='create_room'),
    path('edit_room/<int:room_id>/', PublicChatRoomEditView.as_view(), name='edit_room'),

    path('add_member/<str:room_id>/<str:username>/', add_member_to_room, name='add_member_to_room'),
    path('remove_member/<str:room_id>/<str:username>/', remove_member_from_room, name='remove_member_from_room'),
    path('search/rooms/<str:query>/', search_chat_rooms, name='search_chat_rooms'),


)
