from django.contrib import admin

from .models import Citation, Question


class CitationInline(admin.TabularInline):
    model = Citation
    extra = 0
    can_delete = False
    readonly_fields = ["document_title", "page_number", "excerpt"]
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["text", "status", "channel", "user", "created_at"]
    list_filter = ["status", "channel"]
    search_fields = ["text", "answer"]
    inlines = [CitationInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
