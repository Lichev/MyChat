from django.shortcuts import render
from django.urls import reverse_lazy
from django.views import generic as views
from .models import PublicChatRoom, Message
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect
from .models import PublicChatRoom
from .forms import PublicChatRoomForm
from django.db.models import Q, Max, F


def get_public_chat_rooms():
    # Annotate each room with the maximum timestamp of its messages
    rooms_with_latest_message = PublicChatRoom.objects.annotate(
        latest_message_timestamp=Max('message__timestamp')
    )

    # Order the rooms by the latest message timestamp in descending order
    sorted_rooms = rooms_with_latest_message.order_by(
        F('latest_message_timestamp').desc(nulls_last=True)
    )

    return sorted_rooms


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
        context['members_len'] = current_room.members.count()
        current_user = self.request.user
        is_admin = current_room.is_admin(current_user)
        context['is_admin'] = is_admin

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


class PublicChatRoomEditView(LoginRequiredMixin, UserPassesTestMixin, views.UpdateView):
    model = PublicChatRoom
    form_class = PublicChatRoomForm
    template_name = 'chat_rooms/edit_room.html'
    pk_url_kwarg = 'room_id'
    success_url = reverse_lazy('public_chat_room')

    def test_func(self):
        return self.request.user.is_authenticated

    def get_object(self, queryset=None):
        room_id = self.kwargs.get(self.pk_url_kwarg)
        return PublicChatRoom.objects.get(id=room_id)

    def get_queryset(self):
        return PublicChatRoom.objects.filter(Q(admins=self.request.user) | Q(creator=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['public_chat_rooms'] = get_public_chat_rooms()
        context['room'] = self.get_object()
        context['is_admin'] = context['room'].is_admin(self.request.user)
        return context
