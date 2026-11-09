from django.contrib import admin

from .models import Document, Page
from .services import requeue


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
    list_display = ["title", "status", "page_count", "error_message", "uploaded_at"]
    list_filter = ["status"]
    search_fields = ["title"]
    readonly_fields = ["status", "error_message", "page_count", "uploaded_at"]
    inlines = [PageInline]
    actions = ["reprocess"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # New documents start as pending. A replaced file must be indexed again.
        if change and "file" in form.changed_data:
            requeue(Document.objects.filter(pk=obj.pk))

    @admin.action(description="Process selected documents again")
    def reprocess(self, request, queryset):
        requeue(queryset)
        self.message_user(request, "Queued for processing. The worker will pick them up.")
