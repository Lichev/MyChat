from django.urls import path, include
from CHAT.views import ChatHubView, search_unified, chat_info_json, chat_search_page

urlpatterns = [
    path('', ChatHubView.as_view(), name='public_chat_room'),
    path('search/', search_unified, name='search_unified'),
    path('search/results/', chat_search_page, name='chat_search'),
    path('info/', chat_info_json, name='chat_info'),
    path('rooms/', include('CHAT_ROOMS.urls')),
]
