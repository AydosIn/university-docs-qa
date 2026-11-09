from django.conf import settings
from django.db import models

from documents.models import Document


class Question(models.Model):
    """One question and its answer. Staff insights are built from these."""

    class Status(models.TextChoices):
        ANSWERED = "answered", "Answered"
        NOT_FOUND = "not_found", "Not found in documents"
        ERROR = "error", "Error"

    class Channel(models.TextChoices):
        WEB = "web", "Web"
        TELEGRAM = "telegram", "Telegram"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="questions",
    )
    channel = models.CharField(max_length=20, choices=Channel.choices, default=Channel.WEB)
    external_user_id = models.CharField(max_length=64, blank=True)
    text = models.TextField()
    answer = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.text[:80]

    def margin_pages(self):
        """Citations with repeats of the same page removed."""
        unique = {}
        for citation in self.citations.all():
            unique.setdefault((citation.document_title, citation.page_number), citation)
        return list(unique.values())


class Citation(models.Model):
    """A source for an answer.

    Chunks are replaced whenever a document is processed again, so the title,
    page and excerpt are copied here to keep old answers intact.
    """

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="citations")
    document = models.ForeignKey(Document, on_delete=models.SET_NULL, null=True, blank=True)
    document_title = models.CharField(max_length=255)
    page_number = models.PositiveIntegerField()
    excerpt = models.TextField()

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.document_title}, page {self.page_number}"
