from django.urls import path
from . import views

app_name = "chat"

urlpatterns = [
    path("", views.chat_home, name="home"),
    path("new/", views.conversation_new, name="new"),
    path("<uuid:pk>/", views.conversation_detail, name="detail"),
    path("<uuid:pk>/send/", views.send_message, name="send"),
    path("<uuid:pk>/stream/", views.stream_response, name="stream"),
    path("<uuid:pk>/archive/", views.conversation_archive, name="archive"),
    path("<uuid:pk>/title/", views.conversation_title, name="title"),
    path("sidebar/", views.conversation_sidebar, name="sidebar"),
]
