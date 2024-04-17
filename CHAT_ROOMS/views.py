from django.shortcuts import render
from django.urls import reverse_lazy
from django.views import generic as views
from .models import PublicChatRoom, Message
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect
from .models import PublicChatRoom
from .forms import PublicChatRoomForm
from django.db.models import Q, Max, F
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from functools import reduce
import operator
from FRIEND.models import Friend

UserModel = get_user_model()


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


@login_required
def add_member_to_room(request, room_id, username):
    room = get_object_or_404(PublicChatRoom, id=room_id)
    user = get_object_or_404(UserModel, username=username)

    room.members.add(user)
    room.save()

    members_count = room.members.count()

    return JsonResponse({
        'status': 'Member added successfully',
        'members_count': members_count
    })


@login_required
def remove_member_from_room(request, room_id, username):
    room = get_object_or_404(PublicChatRoom, id=room_id)
    user = get_object_or_404(UserModel, username=username)

    room.members.remove(user)
    room.save()

    return JsonResponse({'status': 'Member removed successfully'})


@login_required
def search_chat_rooms(request, query):
    search_fields = ['name']

    results = PublicChatRoom.objects.all()

    if query:
        query_list = query.split()
        filter_conditions = [Q(**{field + '__icontains': term}) for field in search_fields for term in query_list]
        results = results.filter(reduce(operator.or_, filter_conditions))

    data = list(results.values('id', 'name', 'room_picture'))

    return JsonResponse({'data': data})


@login_required()
def chat_rooms_info_json(request):
    user = request.user

    friends_data = []
    my_groups_data = []

    if user:
        friends = Friend.objects.friends(user)
        my_groups = PublicChatRoom.objects.filter(creator=user.pk)

        for friend in friends:
            friends_data.append({
                'id': friend.id,
                'username': friend.username,
                'avatar': friend.profile_picture.url
            })

        for group in my_groups:
            my_groups_data.append({
                'id': group.id,
                'name': group.name,
                'avatar': group.room_picture.url
            })

    return JsonResponse({'friends': friends_data, 'groups_data': my_groups_data})
