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
from django.contrib.auth.decorators import login_required

UserModel = get_user_model()


def get_friendship_context_object_name():
    return getattr(settings, "FRIENDSHIP_CONTEXT_OBJECT_NAME", "user")


def get_friendship_context_object_list_name():
    return getattr(settings, "FRIENDSHIP_CONTEXT_OBJECT_LIST_NAME", "users")


@login_required
def friendship_add_friend(request, to_username):
    """Create a FriendshipRequest"""
    ctx = {"to_username": to_username}

    if request.method == "POST":
        to_user = UserModel.objects.get(username=to_username)
        from_user = request.user
        try:
            Friend.objects.add_friend(from_user, to_user)
        except AlreadyExistsError as e:
            ctx["errors"] = ["%s" % e]
        else:
            referer = request.META.get('HTTP_REFERER')
            if referer:
                return redirect(referer)
            else:
                return HttpResponseBadRequest("HTTP Referer header not present.")

    return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def friendship_accept(request, friendship_request_id):
    """Accept a friendship request"""
    if request.method == "POST":
        f_request = get_object_or_404(
            FriendshipRequest.objects.filter(id=friendship_request_id),  # Adjusted filter
        )
        f_request.accept()
        return redirect(request.META.get('HTTP_REFERER', '/'))

    return redirect(request.META.get('HTTP_REFERER', '/'), )


@login_required
def friendship_reject(request, friendship_request_id):
    """Reject a friendship request"""
    if request.method == "POST":
        f_request = get_object_or_404(
            FriendshipRequest.objects.filter(id=friendship_request_id),  # Adjusted filter
        )
        f_request.cancel()
        return redirect(request.META.get('HTTP_REFERER', '/'))

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
    print(friend)
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
        'query': query
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
            from_user = UserModel.objects.get(pk=friend_request.from_user_id)
            accounts.append((friend_request, from_user))

    else:
        accounts = UserModel.objects.none()

    paginator = Paginator(accounts, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query
    }

    return render(request, 'friend/friends_requests.html', context)
