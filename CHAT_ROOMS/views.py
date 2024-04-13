from django.shortcuts import render
from django.urls import reverse_lazy
from django.views import generic as views
from .models import PublicChatRoom, Message
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect
from .models import PublicChatRoom
from .forms import PublicChatRoomForm


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
        return Message.objects.filter(room_id=room_id)[0:25]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['public_chat_rooms'] = get_public_chat_rooms()
        room_id = self.kwargs['room_id']
        current_room = PublicChatRoom.objects.get(id=room_id)
        context['current_room'] = current_room
        return context


class PublicChatRoomCreateView(LoginRequiredMixin, UserPassesTestMixin, views.CreateView):
    model = PublicChatRoom
    form_class = PublicChatRoomForm
    template_name = 'chat_rooms/create_room.html'
    success_url = reverse_lazy('public_chat_room')

    def test_func(self):
        return self.request.user.is_authenticated

    def form_valid(self, form):
        form.instance.creator = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['public_chat_rooms'] = get_public_chat_rooms()
        return context
