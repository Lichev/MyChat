import logging

from django.contrib.auth import views as auth_views, get_user_model, login
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from FRIEND.exceptions import AlreadyExistsError
from FRIEND.models import Friend, FriendshipRequest, FriendShipManager
from django.conf import settings
from django.views.generic import ListView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

logger = logging.getLogger(__name__)

UserModel = get_user_model()


def get_friendship_context_object_name():
    return getattr(settings, "FRIENDSHIP_CONTEXT_OBJECT_NAME", "user")


def get_friendship_context_object_list_name():
    return getattr(settings, "FRIENDSHIP_CONTEXT_OBJECT_LIST_NAME", "users")


@login_required
def friendship_add_friend(request, to_username):
    """Create a FriendshipRequest"""
    is_xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == "POST":
        to_user = get_object_or_404(UserModel, username=to_username)
        from_user = request.user
        try:
            friendship_request = Friend.objects.add_friend(from_user, to_user)
        except AlreadyExistsError as e:
            if is_xhr:
                return JsonResponse({'status': 'error', 'detail': str(e)}, status=400)
            return redirect(request.META.get('HTTP_REFERER', '/'))

        if is_xhr:
            return JsonResponse({
                'status': 'ok',
                'request_id': friendship_request.id,
                'receiver_username': to_user.username,
            })

        referer = request.META.get('HTTP_REFERER')
        if referer:
            return redirect(referer)
        return HttpResponseBadRequest("HTTP Referer header not present.")

    if is_xhr:
        return JsonResponse({'status': 'error', 'detail': 'POST required'}, status=405)
    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def friendship_accept(request, friendship_request_id):
    """Accept a friendship request"""
    is_xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == "POST":
        f_request = get_object_or_404(
            FriendshipRequest, id=friendship_request_id, to_user=request.user,
        )
        new_friend = f_request.from_user
        f_request.accept()

        if is_xhr:
            return JsonResponse({
                'status': 'ok',
                'request_id': friendship_request_id,
                'action': 'accepted',
                'new_friend': {
                    'id': new_friend.id,
                    'username': new_friend.username,
                    'avatar': new_friend.profile_picture.url if new_friend.profile_picture else "",
                },
            })
        return redirect(request.META.get('HTTP_REFERER', '/'))

    if is_xhr:
        return JsonResponse({'status': 'error', 'detail': 'POST required'}, status=405)
    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def friendship_reject(request, friendship_request_id):
    """Reject a friendship request"""
    is_xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == "POST":
        f_request = get_object_or_404(
            FriendshipRequest, id=friendship_request_id, to_user=request.user,
        )
        f_request.reject()

        if is_xhr:
            return JsonResponse({
                'status': 'ok',
                'request_id': friendship_request_id,
                'action': 'rejected',
            })
        return redirect(request.META.get('HTTP_REFERER', '/'))

    if is_xhr:
        return JsonResponse({'status': 'error', 'detail': 'POST required'}, status=405)
    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def friendship_cancel(request, friendship_request_id):
    """Cancel a previously created friendship_request_id"""
    if request.method == "POST":
        f_request = get_object_or_404(
            FriendshipRequest.objects.filter(id=friendship_request_id),  # Adjusted filter
        )
        f_request.cancel()
        return redirect(request.META.get('HTTP_REFERER', '/'))

    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def remove_friend_view(request, friend_id):
    """ Remove a friendship between two users """
    friend = get_object_or_404(UserModel, id=friend_id)
    user = request.user
    logger.debug("remove_friend_view: user=%s removing friend=%s", user, friend)
    if request.method == "POST":
        Friend.objects.remove_friend(user, friend)

        return redirect(request.META.get('HTTP_REFERER', '/'))

    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def show_friends_view(request, ):
    query = request.GET.get('query', '')
    user = request.user
    accounts = []  # [(account1, get_user_context), (account2, get_user_context),]

    if user:
        result = Friend.objects.friends(user)
        for account in result:
            accounts.append(account)

    else:
        accounts = UserModel.objects.none()

    paginator = Paginator(accounts, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query,
        'active_tab': 'account',
    }

    return render(request, 'friend/friends_list.html', context)


@login_required
def show_friends_request(request):
    query = request.GET.get('query', '')
    user = request.user
    accounts = []  # [(request, from_user), (request, from_user),]

    if user:
        result = Friend.objects.requests(user)
        for friend_request in result:
            # from_user is already select_related by FriendShipManager.requests() —
            # no extra DB query needed here.
            accounts.append((friend_request, friend_request.from_user))

    else:
        accounts = UserModel.objects.none()

    paginator = Paginator(accounts, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query,
        'active_tab': 'account',
    }

    return render(request, 'friend/friends_requests.html', context)
