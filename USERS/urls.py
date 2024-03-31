from django.contrib import admin
from django.urls import path, include
from USERS.views import LogoutView, RegisterView, LoginView, EmailVerificationView, ActivateUserView, DetailUserView, \
    ProfileSettingsView, ProfileSettingsName, ProfileSettingsInfo, search_view, PublicUserView, ProfileSettingsAvatar
from django.contrib.auth import views as auth_views

urlpatterns = (
    path('password_reset/',
         auth_views.PasswordResetView.as_view(template_name='users/password_reset/password_reset_form.html',
                                              email_template_name='users/password_reset/password_reset_email.html'),
         name='password_reset'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('email_verification/', EmailVerificationView.as_view(), name='email'),
    path('activate-user/<uidb64>/<token>', ActivateUserView.as_view(), name='activate-user'),
    path('profile/<int:pk>/', include(([
        path('', DetailUserView.as_view(), name='profile'),
        path('settings/', include(([
            path('', ProfileSettingsView.as_view(), name='profile-settings'),
            path('name/', ProfileSettingsName.as_view(), name='profile-settings-name'),
            path('personal-info/', ProfileSettingsInfo.as_view(), name='profile-settings-info'),
            path('avatar/', ProfileSettingsAvatar.as_view(), name='profile-settings-avatar')
        ]))),
        # path('delete/', DeleteUserView.as_view(), name='profile-delete'),
    ]))),
    path('search/', search_view, name='search-results'),

    path('<str:username>/', PublicUserView.as_view(), name='public-profile'),

    path('password_change/done/',
         auth_views.PasswordChangeDoneView.as_view(template_name='users/password_reset/password_change_done.html'),
         name='password_change_done'),

    # path('password_change/',
    #      auth_views.PasswordChangeView.as_view(template_name='users/password_reset/password_change.html'),
    #      name='password_change'),

    path('password_reset/done/',
         auth_views.PasswordResetCompleteView.as_view(template_name='users/password_reset/password_reset_done.html'),
         name='password_reset_done'),

    path('reset/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(template_name='users/password_reset/password_change.html'),
         name='password_reset_confirm'),

    path('reset/done/',
         auth_views.PasswordResetCompleteView.as_view(
             template_name='users/password_reset/password_reset_complete.html'),
         name='password_reset_complete'),
)
