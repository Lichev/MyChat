from django.shortcuts import render
from django.views.generic import TemplateView
from django.contrib.auth import views as auth_views, get_user_model, login


class HomePage(TemplateView):
    template_name = 'core/index.html'



