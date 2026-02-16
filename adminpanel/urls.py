from django.urls import path
from . import views

app_name = "adminpanel"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # Documents
    path("documents/", views.admin_documents, name="documents"),
    path("documents/upload/", views.admin_document_upload, name="document_upload"),
    path("documents/bulk-delete/", views.admin_documents_bulk_delete, name="documents_bulk_delete"),
    path("documents/<uuid:pk>/", views.admin_document_detail, name="document_detail"),
    path("documents/<uuid:pk>/delete/", views.admin_document_delete, name="document_delete"),
    path("documents/<uuid:pk>/reupload/", views.admin_document_reupload, name="document_reupload"),
    # Conversations
    path("conversations/", views.admin_conversations, name="conversations"),
    path("conversations/bulk-delete/", views.admin_conversations_bulk_delete, name="conversations_bulk_delete"),
    path("conversations/<uuid:pk>/", views.admin_conversation_detail, name="conversation_detail"),
    path("conversations/<uuid:pk>/delete/", views.admin_conversation_delete, name="conversation_delete"),
    # Users
    path("users/", views.admin_users, name="users"),
    path("users/add/", views.admin_user_add, name="user_add"),
    path("users/<uuid:pk>/edit/", views.admin_user_edit, name="user_edit"),
    path("users/<uuid:pk>/delete/", views.admin_user_delete, name="user_delete"),
    # Masquerade
    path("masquerade/<uuid:user_id>/start/", views.masquerade_start, name="masquerade_start"),
    path("masquerade/stop/", views.masquerade_stop, name="masquerade_stop"),
    # Usage & Export
    path("usage/", views.admin_usage, name="usage"),
    path("usage/export/", views.admin_usage_export, name="usage_export"),
    # Vector Store
    path("vector-store/", views.admin_vector_store, name="vector_store"),
    # Settings
    path("settings/", views.admin_settings, name="settings"),
    # Drive
    path("drive/", views.admin_drive_settings, name="drive_settings"),
    path("drive/sync/", views.admin_drive_sync, name="drive_sync"),
    # Raw Log
    path("raw-log/", views.admin_raw_log, name="raw_log"),
]
