from django.shortcuts import render
from django.urls import reverse_lazy
from django.views import generic as views
from .models import PublicChatRoom, Message
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from .models import PublicChatRoom
from .forms import PublicChatRoomForm
from django.db.models import Q, Max, F, Subquery, OuterRef
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from functools import reduce
import operator
from FRIEND.models import Friend

UserModel = get_user_model()

PAGE_SIZE = 25


def get_public_chat_rooms():
    # Annotate each room with the maximum timestamp of its messages
    rooms_with_latest_message = PublicChatRoom.objects.annotate(
        latest_message_timestamp=Max('messages__timestamp')
    )

    # Order the rooms by the latest message timestamp in descending order
    sorted_rooms = rooms_with_latest_message.order_by(
        F('latest_message_timestamp').desc(nulls_last=True)
    )

    return sorted_rooms


def get_last_messages_preview(rooms):
    """Return a dict {room_id: last_message_preview_str} for the given rooms queryset.

    Uses a single subquery per room — no N+1.
    The preview is truncated to 80 characters for sidebar display.
    """
    latest_message_ids = (
        Message.objects
        .filter(room=OuterRef('pk'))
        .order_by('-timestamp')
        .values('id')[:1]
    )
    rooms_with_last = rooms.annotate(last_message_id=Subquery(latest_message_ids))

    last_message_ids = [r.last_message_id for r in rooms_with_last if r.last_message_id]
    messages = (
        Message.objects
        .filter(id__in=last_message_ids)
        .select_related('sender')
    )
    msg_by_id = {m.id: m for m in messages}

    preview = {}
    for room in rooms_with_last:
        msg = msg_by_id.get(room.last_message_id)
        if msg:
            content = msg.content if len(msg.content) <= 60 else msg.content[:57] + '...'
            preview[room.id] = {
                'sender': msg.sender.username,
                'content': content,
                'timestamp': msg.timestamp.isoformat(),
            }
        else:
            preview[room.id] = None
    return preview


# Create your views here.
class PublicChatRoomView(LoginRequiredMixin, views.TemplateView):
    template_name = 'chat_rooms/public_chat_rooms.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rooms = get_public_chat_rooms()
        context['public_chat_rooms'] = rooms
        context['last_messages'] = get_last_messages_preview(rooms)
        return context


class PublicChatRoomMessages(LoginRequiredMixin, views.ListView):
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


class PublicChatRoomCreateView(LoginRequiredMixin, views.CreateView):
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


class PublicChatRoomEditView(LoginRequiredMixin, views.UpdateView):
    model = PublicChatRoom
    form_class = PublicChatRoomForm
    template_name = 'chat_rooms/edit_room.html'
    pk_url_kwarg = 'room_id'
    success_url = reverse_lazy('public_chat_room')

    def get_object(self, queryset=None):
        room_id = self.kwargs.get(self.pk_url_kwarg)
        return get_object_or_404(PublicChatRoom, id=room_id)

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
            'room_picture_url': request.build_absolute_uri(room.room_picture.url),
        }
        for room in results
    ]

    return JsonResponse({'data': data})


@login_required
def chat_rooms_info_json(request):
    user = request.user

    friends = Friend.objects.friends(user)
    my_groups = PublicChatRoom.objects.filter(creator=user)
    requests_count = len(Friend.objects.requests(user))

    friends_data = [
        {
            'id': friend.id,
            'username': friend.username,
            'avatar': friend.profile_picture.url,
        }
        for friend in friends
    ]
    my_groups_data = [
        {
            'id': group.id,
            'name': group.name,
            'avatar': group.room_picture.url,
        }
        for group in my_groups
    ]

    return JsonResponse({'friends': friends_data, 'groups_data': my_groups_data, 'requests_count': requests_count})
