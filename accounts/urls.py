from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path("profile/", views.profile_view, name="profile"),
    path("login-redirect/", views.login_redirect_view, name="login_redirect"),
]
