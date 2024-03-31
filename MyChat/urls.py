from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('CORE.urls')),
    path('accounts/', include('USERS.urls')),
    path('friend/', include('FRIEND.urls')),
    path('rooms/', include('CHAT_ROOMS.urls')),

]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
