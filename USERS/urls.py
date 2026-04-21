from django.urls import path, include
from USERS.views import (
    LogoutView, RegisterView, LoginView,
    DetailUserView, ProfileSettingsView, ProfileSettingsName, ProfileSettingsInfo,
    search_view, PublicUserView, ProfileSettingsAvatar,
    RecoverAccountView, ProfileSettingsSecurityView, dismiss_key_banner,
)
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('password_change/done/',
         auth_views.PasswordChangeDoneView.as_view(
             template_name='users/password_reset/password_change_done.html'),
         name='password_change_done'),

    path('logout/', LogoutView.as_view(), name='logout'),
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),

    # Recovery key password-reset flow
    path('recover/', RecoverAccountView.as_view(), name='account_recover'),
    path('dismiss-key-banner/', dismiss_key_banner, name='dismiss_key_banner'),

    path('profile/<int:pk>/', include(([
        path('', DetailUserView.as_view(), name='profile'),
        path('settings/', include(([
            path('', ProfileSettingsView.as_view(), name='profile-settings'),
            path('name/', ProfileSettingsName.as_view(), name='profile-settings-name'),
            path('personal-info/', ProfileSettingsInfo.as_view(), name='profile-settings-info'),
            path('avatar/', ProfileSettingsAvatar.as_view(), name='profile-settings-avatar'),
            path('security/', ProfileSettingsSecurityView.as_view(), name='profile-settings-security'),
        ]))),
    ]))),
    path('search/', search_view, name='search-results'),

    # Keep last — single-segment catch-all for public profile pages
    path('<str:username>/', PublicUserView.as_view(), name='public-profile'),
]
