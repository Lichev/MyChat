import logging
import secrets
import time

from django.contrib.auth import views as auth_views, get_user_model, login
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import generic as views
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.utils.decorators import method_decorator
from .forms import RegisterUserForm, ProfileSettingsNameForm, ProfileSettingsAvatarForm
from django.contrib import messages
from django.urls import reverse
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator

CONTACT_FORM_COOLDOWN_SECONDS = 60

logger = logging.getLogger(__name__)

from FRIEND.models import Friend, FriendshipRequest, FriendShipManager
from .rate_limit import is_rate_limited, record_failed_attempt, get_attempt_count, clear_attempts

UserModel = get_user_model()


@require_POST
@login_required
def dismiss_key_banner(request):
    request.session.pop('show_key_banner', None)
    return HttpResponse(status=204)


@require_POST
def send_contact_message(request):
    # Session-based rate limit: one submission per CONTACT_FORM_COOLDOWN_SECONDS.
    # Note: for unauthenticated visitors this only works if the client maintains
    # session cookies. A cookieless client can bypass the cooldown. This is an
    # acceptable limitation for a public contact form — add IP-based rate limiting
    # (e.g. django-ratelimit) for stronger protection in production.
    last_sent = request.session.get('contact_form_last_sent', 0)
    now = time.time()
    if now - last_sent < CONTACT_FORM_COOLDOWN_SECONDS:
        wait = int(CONTACT_FORM_COOLDOWN_SECONDS - (now - last_sent))
        messages.error(request, f'Please wait {wait} seconds before sending another message.')
        return redirect('mail_success')

    name = request.POST.get('name', '').strip()
    sender_email = request.POST.get('emailaddress', '').strip()
    message = request.POST.get('subject', '').strip()

    if not name or not sender_email or not message:
        messages.error(request, 'All fields are required.')
        return redirect('mail_success')

    # Construct email — use the server's own address as from_email to
    # prevent spoofing; include the sender's address in the body.
    email_subject = 'New contact form submission on MyChat'
    email_body = render_to_string('core/contact_form_email.txt', {
        'name': name,
        'email': sender_email,
        'message': message,
    })
    email = EmailMessage(
        subject=email_subject,
        body=email_body,
        from_email=settings.EMAIL_FROM_USER,
        to=[settings.EMAIL_HOST_USER],
    )
    try:
        email.send()
    except Exception:
        logger.exception("Failed to send contact form email from %s", sender_email)

    # Record the send time so the cooldown check above applies on the next request.
    request.session['contact_form_last_sent'] = time.time()

    return redirect('mail_success')


def get_user_context(account, user):
    context = {}

    is_friend = Friend.objects.are_friends(account, user)
    has_sent_request = FriendshipRequest.objects.filter(from_user=user, to_user=account).exists()
    has_received_request = FriendshipRequest.objects.filter(from_user=account, to_user=user).exists()
    friends_len = len(Friend.objects.friends(account))

    if has_received_request:
        request = FriendshipRequest.objects.filter(from_user=account, to_user=user).first()
        context['request_id'] = request.id

    if has_sent_request:
        request = FriendshipRequest.objects.filter(from_user=user, to_user=account).first()
        context['request_id'] = request.id

    context['is_self'] = user == account
    context['to_username'] = account
    context['is_friend'] = is_friend
    context['has_sent_request'] = has_sent_request
    context['has_received_request'] = has_received_request
    context['friends_len'] = friends_len

    return context


class LogoutView(auth_views.LogoutView):
    pass


@method_decorator(sensitive_post_parameters('password1', 'password2'), name='dispatch')
@method_decorator(sensitive_variables('raw_key'), name='dispatch')
class RegisterView(views.CreateView):
    template_name = 'users/register.html'
    form_class = RegisterUserForm
    success_url = reverse_lazy('index')

    def form_valid(self, form):
        # Save user first so we have a PK.
        user = form.save()
        self.object = user

        # Generate the one-time recovery key — 256 bits of entropy.
        # raw_key is shown to the user exactly once and never stored in plaintext.
        raw_key = secrets.token_urlsafe(32)
        user.recovery_key_hash = make_password(raw_key)
        user.recovery_key_created_at = timezone.now()
        user.save(update_fields=['recovery_key_hash', 'recovery_key_created_at'])

        login(self.request, user)

        # Flag consumed by base.html to show the one-time reminder banner on the next page.
        self.request.session['show_key_banner'] = True

        # Render the key-reveal page directly so raw_key never touches a session,
        # cache, or redirect parameter. Cache-Control: no-store prevents browser caching.
        # raw_key_chunked: groups of 4 chars for readability in the monospace display block.
        raw_key_chunked = '-'.join(raw_key[i:i+4] for i in range(0, len(raw_key), 4))
        response = render(self.request, 'users/key_reveal.html', {
            'raw_key': raw_key,
            'raw_key_chunked': raw_key_chunked,
        })
        response['Cache-Control'] = 'no-store'
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['next'] = self.request.GET.get('next', '')
        return context


class LoginView(auth_views.LoginView):
    template_name = 'users/login.html'

    def form_valid(self, form):
        return super().form_valid(form)


class DetailUserView(LoginRequiredMixin, UserPassesTestMixin, views.DetailView):
    model = UserModel
    template_name = 'users/profile-personal-card.html'

    def test_func(self):
        # This method is used by UserPassesTestMixin to check if the user passes the test
        return self.request.user == self.get_object()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        friends_len = Friend.objects.friends(user)
        friend_requests = Friend.objects.requests(user)

        context['friends_len'] = len(friends_len)
        context['requests_len'] = len(friend_requests)

        return context


class PublicUserView(LoginRequiredMixin, views.DetailView):
    model = UserModel
    template_name = 'users/profile-public-card.html'

    def get_object(self):
        username = self.kwargs.get('username')
        return get_object_or_404(UserModel, username=username)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        account = self.object  # already fetched by DetailView — avoids a second DB query
        user = self.request.user

        context.update(get_user_context(account, user))

        return context


class ProfileSettingsView(LoginRequiredMixin, UserPassesTestMixin, views.DetailView):
    template_name = 'users/profile-settings.html'
    model = UserModel

    def test_func(self):
        return self.request.user == self.get_object()


class ProfileSettingsName(LoginRequiredMixin, UserPassesTestMixin, views.UpdateView):
    model = UserModel
    template_name = 'users/profile-settings-name.html'
    form_class = ProfileSettingsNameForm

    def test_func(self):
        return self.request.user == self.get_object()

    def get_success_url(self):
        user_pk = self.request.user.pk
        return reverse('profile-settings-name', args=[user_pk])


class ProfileSettingsAvatar(LoginRequiredMixin, UserPassesTestMixin, views.UpdateView):
    model = UserModel
    template_name = 'users/profile-settings-avatar.html'
    form_class = ProfileSettingsAvatarForm

    def test_func(self):
        return self.request.user == self.get_object()

    def get_success_url(self):
        user_pk = self.request.user.pk
        return reverse('profile-settings-avatar', args=[user_pk])


class ProfileSettingsInfo(LoginRequiredMixin, UserPassesTestMixin, views.UpdateView):
    model = UserModel
    template_name = 'users/profile-settings-info.html'

    fields = [
        'gender',
        'phone_number',
        'date_of_birth',
        'city',
        'country',
    ]

    def test_func(self):
        return self.request.user == self.get_object()

    def get_success_url(self):
        user_pk = self.request.user.pk
        return reverse('profile-settings-info', args=[user_pk])


@method_decorator(sensitive_post_parameters('new_password1', 'new_password2'), name='dispatch')
@method_decorator(sensitive_variables('raw_key'), name='dispatch')
class ProfileSettingsSecurityView(LoginRequiredMixin, views.View):
    template_name = 'users/profile-settings-security.html'

    def _get_user(self):
        return self.request.user

    def get(self, request, pk):
        if request.user.pk != pk:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        user = self._get_user()
        return render(request, self.template_name, {
            'object': user,
            'has_key': bool(user.recovery_key_hash),
        })

    def post(self, request, pk):
        if request.user.pk != pk:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        user = self._get_user()
        action = request.POST.get('action')

        if action == 'rotate_key':
            raw_key = secrets.token_urlsafe(32)
            user.recovery_key_hash = make_password(raw_key)
            user.recovery_key_created_at = timezone.now()
            user.save(update_fields=['recovery_key_hash', 'recovery_key_created_at'])

            raw_key_chunked = '-'.join(raw_key[i:i+4] for i in range(0, len(raw_key), 4))
            response = render(request, 'users/key_reveal.html', {
                'raw_key': raw_key,
                'raw_key_chunked': raw_key_chunked,
                'is_rotation': True,
            })
            response['Cache-Control'] = 'no-store'
            return response

        if action == 'change_password':
            old_password = request.POST.get('old_password', '')
            new_password1 = request.POST.get('new_password1', '')
            new_password2 = request.POST.get('new_password2', '')

            if not user.check_password(old_password):
                return render(request, self.template_name, {
                    'object': user,
                    'has_key': bool(user.recovery_key_hash),
                    'pw_error': 'Current password is incorrect.',
                })
            if new_password1 != new_password2:
                return render(request, self.template_name, {
                    'object': user,
                    'has_key': bool(user.recovery_key_hash),
                    'pw_error': 'The two passwords do not match.',
                })
            try:
                validate_password(new_password1, user)
            except ValidationError as e:
                return render(request, self.template_name, {
                    'object': user,
                    'has_key': bool(user.recovery_key_hash),
                    'pw_errors': e.messages,
                })
            user.set_password(new_password1)
            user.save(update_fields=['password'])
            login(request, user)
            messages.success(request, 'Password updated successfully.')
            return redirect(reverse('profile-settings-security', args=[user.pk]))

        return redirect(reverse('profile-settings-security', args=[user.pk]))


@login_required
def search_view(request, *args, **kwargs):
    query = request.GET.get('query', '')
    user = request.user
    accounts = []  # [(account1, get_user_context), (account2, get_user_context),]

    if query:
        result = UserModel.objects.filter(username__icontains=query)
        for account in result:
            accounts.append((account, get_user_context(account, user)))

    else:
        accounts = UserModel.objects.none()

    paginator = Paginator(accounts, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query
    }

    return render(request, 'users/search-results.html', context)


# Dummy hash used when the requested username does not exist.
# Performing a full comparison against this value (which will always fail)
# ensures the response time is indistinguishable from a real failed attempt,
# preventing timing-based username enumeration.
_DUMMY_HASH = make_password('__dummy_sentinel__')


def _get_client_ip(request) -> str:
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


@method_decorator(sensitive_post_parameters('recovery_key', 'new_password1', 'new_password2'), name='dispatch')
class RecoverAccountView(views.View):
    """Single-step recovery: username + recovery key + new password in one form."""
    template_name = 'users/recover_account.html'

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        username = request.POST.get('username', '').strip()
        raw_key = request.POST.get('recovery_key', '').strip()
        new_password1 = request.POST.get('new_password1', '')
        new_password2 = request.POST.get('new_password2', '')
        ip = _get_client_ip(request)

        # Rate-limit check before any DB or hash work.
        if is_rate_limited(username):
            return render(request, self.template_name, {
                'is_locked_out': True,
                'show_dead_end': True,
            })

        try:
            user = UserModel.objects.get(username=username)
            stored_hash = user.recovery_key_hash or _DUMMY_HASH
        except UserModel.DoesNotExist:
            user = None
            stored_hash = _DUMMY_HASH

        key_valid = check_password(raw_key, stored_hash)

        if not key_valid or user is None:
            count = record_failed_attempt(username, ip)
            return render(request, self.template_name, {
                'key_error': 'Invalid username or recovery key.',
                'show_dead_end': count >= 3,
            })

        # Key verified — now validate the new password before committing anything.
        if new_password1 != new_password2:
            return render(request, self.template_name, {
                'error': 'The two passwords do not match.',
            })

        try:
            validate_password(new_password1, user)
        except ValidationError as e:
            return render(request, self.template_name, {
                'errors': e.messages,
            })

        user.set_password(new_password1)
        user.recovery_key_hash = None
        user.recovery_key_created_at = None
        user.save(update_fields=['password', 'recovery_key_hash', 'recovery_key_created_at'])

        # Invalidate all existing sessions for this user so any other active
        # devices are forced to re-authenticate with the new password.
        from django.contrib.sessions.backends.db import SessionStore
        from django.contrib.sessions.models import Session
        from django.contrib.auth import SESSION_KEY
        for session in Session.objects.all():
            data = session.get_decoded()
            if str(data.get(SESSION_KEY)) == str(user.pk):
                session.delete()

        clear_attempts(user.username)

        logger.info(
            "Password reset via recovery key: user_id=%s ip=%s",
            user.pk, ip,
        )

        messages.success(request, 'Password updated. Sign in with your new password.')
        return redirect(reverse('login'))
