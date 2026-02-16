from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect

urlpatterns = [
    path("accounts/", include("allauth.urls")),
    path("accounts/", include("accounts.urls")),
    path("chat/", include("chat.urls")),
    path("documents/", include("documents.urls")),
    path("panel/", include("adminpanel.urls")),
    path("", lambda r: redirect("chat:home")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
