from django.contrib.auth import views as auth_views, get_user_model, login
from django.db.models import Q
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.views import generic as views
from django.views.generic import TemplateView
from .forms import RegisterUserForm, ProfileSettingsNameForm, ProfileSettingsAvatarForm
from django.contrib import messages
from django.urls import reverse
from django.contrib.sites.shortcuts import get_current_site
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str, DjangoUnicodeDecodeError
from .utils import generate_token
from django.core.mail import EmailMessage
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator

from FRIEND.models import Friend, FriendshipRequest, FriendShipManager

UserModel = get_user_model()


def send_activation_email(user, request):
    current_site = get_current_site(request)
    email_subject = 'Activate your MyChat account'
    email_body = render_to_string('users/activate.html', {
        'user': user,
        'domain': current_site,
        'uid': urlsafe_base64_encode(force_bytes(user.pk)),
        'token': generate_token.make_token(user)
    })

    email = EmailMessage(subject=email_subject,
                         body=email_body,
                         from_email=settings.EMAIL_FROM_USER,
                         to=[user.email]
                         )
    email.send()


def get_user_context(account, user):
    context = {}

    is_friend = Friend.objects.are_friends(account, user)
    has_sent_request = FriendshipRequest.objects.filter(from_user=user, to_user=account).exists()
    has_received_request = FriendshipRequest.objects.filter(from_user=account, to_user=user).exists()
    friends_len = len(Friend.objects.filter(from_user=account))

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


class RegisterView(views.CreateView):
    template_name = 'users/register.html'
    form_class = RegisterUserForm
    success_url = reverse_lazy('index')

    def form_valid(self, form):
        result = super().form_valid(form)
        user = self.object

        if user.is_email_verified:
            login(self.request, user)
            return result
        else:
            send_activation_email(user, self.request)
            return redirect(reverse('email'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['next'] = self.request.GET.get('next', '')

        return context

    def get_success_url(self):
        return self.request.POST.get('next', self.success_url)


class LoginView(auth_views.LoginView):
    template_name = 'users/login.html'

    def form_valid(self, form):
        user = form.get_user()
        if user:
            if user.is_email_verified:
                login(self.request, user)
                return super().form_valid(form)
            else:
                messages.error(self.request, 'Your email is not verified.')
                return self.form_invalid(form)
        else:
            messages.error(self.request, 'Invalid username or password.')
            return self.form_invalid(form)


class EmailVerificationView(TemplateView):
    template_name = 'users/email_confirmation.html'


class ActivateUserView(views.View):
    def get(self, request, uidb64, token):
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = UserModel.objects.get(pk=uid)

        except (TypeError, ValueError, OverflowError, UserModel.DoesNotExist):
            user = None

        if user and generate_token.check_token(user, token):
            user.is_email_verified = True
            user.save()

            messages.success(request, 'Email verified. You can now log in.')
            return redirect(reverse('login'))

        return render(request, 'users/activate-failed.html', {'user': user})


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

        context['friends_len'] = len(friends_len)

        return context


class PublicUserView(LoginRequiredMixin, views.DetailView):
    model = UserModel
    template_name = 'users/profile-public-card.html'

    def get_object(self):
        username = self.kwargs.get('username')
        return get_object_or_404(UserModel, username=username)

    def get_context_data(self, **kwargs):
        account = self.get_object()  # The user from the current view
        user = self.request.user  # The logged user
        context = super().get_context_data(**kwargs)

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

    fields = [
        'first_name',
        'last_name'
    ]

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

    print(context)

    return render(request, 'users/search-results.html', context)
