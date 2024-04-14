from django.urls import path, include
from CHAT_ROOMS.views import PublicChatRoomView, PublicChatRoomMessages, PublicChatRoomCreateView, PublicChatRoomEditView


urlpatterns = (
        path('', PublicChatRoomView.as_view(), name='public_chat_room'),
        path('rooms/<int:room_id>/', PublicChatRoomMessages.as_view(), name='public_chat_messages'),
        path('create_room/', PublicChatRoomCreateView.as_view(), name='create_room'),
        path('edit_room/<int:room_id>/', PublicChatRoomEditView.as_view(), name='edit_room'),
)
