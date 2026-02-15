from django.contrib import admin
from .models import UsageLog, MasqueradeSession


@admin.register(UsageLog)
class UsageLogAdmin(admin.ModelAdmin):
    list_display = ("user", "domain_classified", "chunks_retrieved", "created_at")
    list_filter = ("domain_classified",)


@admin.register(MasqueradeSession)
class MasqueradeSessionAdmin(admin.ModelAdmin):
    list_display = ("admin_user", "target_user", "started_at", "ended_at")
