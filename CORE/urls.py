from django.contrib import admin
from django.urls import path
from CORE.views import HomePage

urlpatterns = (
    path('', HomePage.as_view(), name='index'),

)
