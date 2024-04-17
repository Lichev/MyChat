from django.contrib import admin
from django.urls import path
from CORE.views import HomePage, ContactSuccessView
from USERS.views import send_contact_message

urlpatterns = (
    path('', HomePage.as_view(), name='index'),
    path('contact-email/', send_contact_message, name='send_contact_message'),
    path('contact-success/', ContactSuccessView.as_view(), name='mail_success'),
)
