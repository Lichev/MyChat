from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views import generic as views

from CHAT_ROOMS.models import PublicChatRoom
from CHAT_ROOMS.services import get_public_chat_rooms, get_last_messages_preview
from FRIEND.models import Friend, FriendshipRequest
from CHAT.mixins import HubShellMixin

UserModel = get_user_model()


def _build_search_data(request, query):
    """Return (rooms_data, users_data) for a given query string."""
    if not query:
        return [], []

    user = request.user

    matched_rooms = PublicChatRoom.objects.filter(name__icontains=query)[:10]
    rooms_data = [
        {
            'id': room.id,
            'name': room.name,
            'room_picture_url': room.room_picture.url if room.room_picture else "",
        }
        for room in matched_rooms
    ]

    matched_users = (
        UserModel.objects
        .filter(username__icontains=query)
        .exclude(pk=user.pk)[:10]
    )

    user_ids = [u.pk for u in matched_users]
    outgoing = set(
        FriendshipRequest.objects
        .filter(from_user=user, to_user_id__in=user_ids, rejected__isnull=True)
        .values_list('to_user_id', flat=True)
    )
    incoming = set(
        FriendshipRequest.objects
        .filter(to_user=user, from_user_id__in=user_ids, rejected__isnull=True)
        .values_list('from_user_id', flat=True)
    )
    friend_ids = set(
        f.pk for f in Friend.objects.friends(user)
        if f.pk in user_ids
    )

    users_data = [
        {
            'id': u.id,
            'username': u.username,
            'avatar': u.profile_picture.url if u.profile_picture else "",
            'is_friend': u.pk in friend_ids,
            'has_pending_outgoing_request': u.pk in outgoing,
            'has_pending_incoming_request': u.pk in incoming,
        }
        for u in matched_users
    ]

    return rooms_data, users_data


class ChatHubView(HubShellMixin, LoginRequiredMixin, views.TemplateView):
    template_name = 'chat/hub.html'
    active_tab = "rooms"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rooms = get_public_chat_rooms()
        context['public_chat_rooms'] = rooms
        context['last_messages'] = get_last_messages_preview(rooms)
        if self.request.GET.get("view") == "users":
            context["active_tab"] = "users"
        return context


@login_required
def search_unified(request):
    query = request.GET.get('q', '').strip()
    rooms_data, users_data = _build_search_data(request, query)
    return JsonResponse({'query': query, 'rooms': rooms_data, 'users': users_data})


@login_required
def chat_search_page(request):
    query = request.GET.get('q', '').strip()
    rooms_data, users_data = _build_search_data(request, query)
    return render(request, 'chat/search_results.html', {
        'query': query,
        'rooms': rooms_data,
        'users': users_data,
    })


@login_required
def chat_info_json(request):
    user = request.user

    friends = Friend.objects.friends(user)
    my_groups = PublicChatRoom.objects.filter(creator=user)

    pending_qs = (
        FriendshipRequest.objects
        .filter(to_user=user, rejected__isnull=True)
        .select_related('from_user')
    )
    pending_requests = [
        {
            'request_id': fr.id,
            'sender_username': fr.from_user.username,
            'sender_avatar': fr.from_user.profile_picture.url if fr.from_user.profile_picture else "",
            'created_at': fr.created.isoformat(),
        }
        for fr in pending_qs
    ]

    friends_data = [
        {
            'id': friend.id,
            'username': friend.username,
            'avatar': friend.profile_picture.url if friend.profile_picture else "",
            'last_dm_preview': None,
        }
        for friend in friends
    ]
    my_groups_data = [
        {
            'id': group.id,
            'name': group.name,
            'avatar': group.room_picture.url if group.room_picture else "",
        }
        for group in my_groups
    ]

    return JsonResponse({
        'friends': friends_data,
        'groups_data': my_groups_data,
        'requests_count': len(pending_requests),
        'pending_requests': pending_requests,
    })
