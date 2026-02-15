from django.contrib import admin
from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "authority_level", "domain", "status", "created_at")
    list_filter = ("authority_level", "domain", "status")
    search_fields = ("title",)
