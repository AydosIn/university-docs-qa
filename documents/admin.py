from django.contrib import admin, messages

from .models import Document, Page
from .services import process_document


class PageInline(admin.StackedInline):
    """Shows the extracted text on each document's admin page."""

    model = Page
    extra = 0
    can_delete = False
    readonly_fields = ["number", "text"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "page_count", "uploaded_at"]
    list_filter = ["status"]
    search_fields = ["title"]
    readonly_fields = ["status", "error_message", "page_count", "uploaded_at"]
    inlines = [PageInline]
    actions = ["reprocess"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change or "file" in form.changed_data:
            process_document(obj)
            if obj.status == Document.Status.FAILED:
                self.message_user(request, obj.error_message, level=messages.ERROR)

    @admin.action(description="Process selected documents again")
    def reprocess(self, request, queryset):
        for document in queryset:
            process_document(document)
        self.message_user(request, f"Processed {queryset.count()} document(s).")
