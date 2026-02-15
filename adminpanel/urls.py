from django.urls import path
from . import views

app_name = "adminpanel"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("documents/", views.admin_documents, name="documents"),
    path("documents/upload/", views.admin_document_upload, name="document_upload"),
    path("documents/<uuid:pk>/", views.admin_document_detail, name="document_detail"),
    path("documents/<uuid:pk>/delete/", views.admin_document_delete, name="document_delete"),
    path("documents/<uuid:pk>/reupload/", views.admin_document_reupload, name="document_reupload"),
    path("conversations/", views.admin_conversations, name="conversations"),
    path("conversations/<uuid:pk>/", views.admin_conversation_detail, name="conversation_detail"),
    path("users/", views.admin_users, name="users"),
    path("masquerade/<uuid:user_id>/start/", views.masquerade_start, name="masquerade_start"),
    path("masquerade/stop/", views.masquerade_stop, name="masquerade_stop"),
    path("usage/", views.admin_usage, name="usage"),
    path("drive/", views.admin_drive_settings, name="drive_settings"),
    path("drive/sync/", views.admin_drive_sync, name="drive_sync"),
    path("raw-log/", views.admin_raw_log, name="raw_log"),
]
