from django.contrib import admin

from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "page_count", "uploaded_at"]
    list_filter = ["status"]
    search_fields = ["title"]
    readonly_fields = ["status", "error_message", "page_count", "uploaded_at"]
