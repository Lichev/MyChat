from django.urls import path

from . import views

app_name = "private_messages"

urlpatterns = [
    path("panic-wipe/", views.panic_wipe_view, name="pm_panic_wipe"),
    path("register-identity/", views.register_identity_view, name="pm_register_identity"),
    path("chat/<int:peer_id>/", views.conversation_view, name="pm_conversation"),
]
