from django.urls import reverse_lazy
from django.views import generic as views
from .models import PublicChatRoom, Message
from django.contrib.auth.mixins import LoginRequiredMixin
from CHAT.mixins import HubShellMixin
from django.shortcuts import redirect
from .forms import PublicChatRoomForm
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from functools import reduce
import operator
from CHAT_ROOMS.services import get_public_chat_rooms, get_last_messages_preview

UserModel = get_user_model()

PAGE_SIZE = 25


class PublicChatRoomMessages(HubShellMixin, LoginRequiredMixin, views.ListView):
    active_tab = "rooms"
    model = Message
    template_name = 'chat_rooms/public_chat_messages.html'
    context_object_name = 'chat_messages'

    def get_queryset(self):
        room_id = self.kwargs['room_id']
        # Fetch the most recent PAGE_SIZE messages (newest-first), then reverse so the
        # template renders them oldest-first (top → bottom), matching WebSocket append order.
        msgs = list(
            Message.objects
            .filter(room_id=room_id)
            .select_related('sender')
            .order_by('-timestamp')[:PAGE_SIZE]
        )
        msgs.reverse()
        return msgs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rooms = get_public_chat_rooms()
        context['public_chat_rooms'] = rooms
        context['last_messages'] = get_last_messages_preview(rooms)
        room_id = self.kwargs['room_id']
        current_room = get_object_or_404(PublicChatRoom, id=room_id)
        context['current_room'] = current_room
        context['room_name'] = current_room.name
        context['members_len'] = current_room.members.count()
        current_user = self.request.user
        context['is_admin'] = current_room.is_admin(current_user)

        # Inform the template whether older messages exist so it can show a "load more" button
        total_count = Message.objects.filter(room_id=room_id).count()
        context['has_more_messages'] = total_count > PAGE_SIZE
        # The oldest message in the current page — used as the cursor for the next page load.
        # oldest_message_id is the primary cursor (ID ordering is stable); timestamp is
        # provided as a secondary convenience value for display purposes.
        qs = context['chat_messages']
        if qs:
            context['oldest_message_id'] = qs[0].pk
            context['oldest_message_timestamp'] = qs[0].timestamp.isoformat()
        else:
            context['oldest_message_id'] = None
            context['oldest_message_timestamp'] = None

        return context


class PublicChatRoomCreateView(HubShellMixin, LoginRequiredMixin, views.CreateView):
    active_tab = "rooms"
    model = PublicChatRoom
    form_class = PublicChatRoomForm
    template_name = 'chat_rooms/create_room.html'
    success_url = reverse_lazy('public_chat_room')

    def form_valid(self, form):
        form.instance.creator = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rooms = get_public_chat_rooms()
        context['public_chat_rooms'] = rooms
        context['last_messages'] = get_last_messages_preview(rooms)
        return context


class PublicChatRoomEditView(HubShellMixin, LoginRequiredMixin, views.UpdateView):
    active_tab = "rooms"
    model = PublicChatRoom
    form_class = PublicChatRoomForm
    template_name = 'chat_rooms/edit_room.html'
    pk_url_kwarg = 'room_id'
    success_url = reverse_lazy('public_chat_room')

    def get_queryset(self):
        return PublicChatRoom.objects.filter(Q(admins=self.request.user) | Q(creator=self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rooms = get_public_chat_rooms()
        context['public_chat_rooms'] = rooms
        context['last_messages'] = get_last_messages_preview(rooms)
        # self.object is already set by UpdateView.get() — avoids a redundant DB query.
        context['room'] = self.object
        context['is_admin'] = self.object.is_admin(self.request.user)
        return context


@require_POST
@login_required
def add_member_to_room(request, room_id, username):
    room = get_object_or_404(PublicChatRoom, id=room_id)
    user = get_object_or_404(UserModel, username=username)

    # Only the joining user may add themselves, or an admin may add others.
    if request.user != user and not room.is_admin(request.user):
        return JsonResponse({'status': 'Forbidden'}, status=403)

    room.members.add(user)
    room.save()

    members_count = room.members.count()

    return JsonResponse({
        'status': 'Member added successfully',
        'members_count': members_count
    })


@require_POST
@login_required
def remove_member_from_room(request, room_id, username):
    room = get_object_or_404(PublicChatRoom, id=room_id)
    user = get_object_or_404(UserModel, username=username)

    # Only the leaving user may remove themselves, or an admin may remove others.
    if request.user != user and not room.is_admin(request.user):
        return JsonResponse({'status': 'Forbidden'}, status=403)

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

    # Build full absolute URLs for room pictures so the JS caller doesn't need
    # to construct media paths manually (previously this broke if MEDIA_URL changed).
    data = [
        {
            'id': room.id,
            'name': room.name,
            'room_picture_url': request.build_absolute_uri(room.room_picture.url) if room.room_picture else "",
        }
        for room in results
    ]

    return JsonResponse({'data': data})


