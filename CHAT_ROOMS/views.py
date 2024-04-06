from django.shortcuts import render
from django.views import generic as views
from .models import PublicChatRoom, Message
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect


def get_public_chat_rooms():
    return PublicChatRoom.objects.all()


# Create your views here.
class PublicChatRoomView(LoginRequiredMixin, UserPassesTestMixin, views.TemplateView):
    template_name = 'chat_rooms/public_chat_rooms.html'

    def test_func(self):
        return self.request.user.is_authenticated

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['public_chat_rooms'] = get_public_chat_rooms()
        return context


class PublicChatRoomMessages(LoginRequiredMixin, UserPassesTestMixin, views.ListView):
    model = Message
    template_name = 'chat_rooms/public_chat_messages.html'
    context_object_name = 'messages'

    def test_func(self):
        return self.request.user.is_authenticated

    def get_queryset(self):
        room_id = self.kwargs['room_id']
        return Message.objects.filter(room_id=room_id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['public_chat_rooms'] = get_public_chat_rooms()
        return context
