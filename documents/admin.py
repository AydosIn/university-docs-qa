from django.contrib import admin

from .models import Collection, Document, Page
from .services import requeue


class PageInline(admin.StackedInline):
    """Shows the extracted text on each document's admin page."""

    model = Page
    extra = 0
    can_delete = False
    readonly_fields = ["number", "text"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ["name", "description", "telegram_enabled"]
    filter_horizontal = ["allowed_groups"]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "collection",
        "status",
        "page_count",
        "replaced_by_newer",
        "error_message",
        "uploaded_at",
    ]
    list_filter = ["status", "collection"]
    search_fields = ["title"]
    readonly_fields = ["status", "error_message", "page_count", "uploaded_at"]
    inlines = [PageInline]
    actions = ["reprocess"]

    @admin.display(boolean=True, description="Replaced")
    def replaced_by_newer(self, obj):
        newer = getattr(obj, "replaced_by", None)
        return newer is not None and newer.status == Document.Status.READY

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # New documents start as pending. A replaced file must be indexed again.
        if change and "file" in form.changed_data:
            requeue(Document.objects.filter(pk=obj.pk))

    @admin.action(description="Process selected documents again")
    def reprocess(self, request, queryset):
        requeue(queryset)
        self.message_user(request, "Queued for processing. The worker will pick them up.")
