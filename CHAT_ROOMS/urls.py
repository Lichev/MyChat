from django.urls import path, include
from CHAT_ROOMS.views import PublicChatRoomView


urlpatterns = (
        path('', PublicChatRoomView.as_view(), name='public_chat_room'),

)
