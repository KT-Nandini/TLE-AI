from django.contrib import admin
from .models import Conversation, Message, ConversationSummary


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "is_archived", "created_at", "updated_at")
    list_filter = ("is_archived",)
    search_fields = ("title", "user__email")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "role", "created_at")
    list_filter = ("role",)


@admin.register(ConversationSummary)
class ConversationSummaryAdmin(admin.ModelAdmin):
    list_display = ("conversation", "created_at")
