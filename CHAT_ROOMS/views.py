from django.shortcuts import render
from django.views.generic import TemplateView


# Create your views here.
class PublicChatRoomView(TemplateView):
    template_name = 'chat_rooms/public_chat_rooms.html'