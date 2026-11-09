from django.core.validators import FileExtensionValidator
from django.db import models

from .validators import validate_pdf


class Document(models.Model):
    """One uploaded PDF, such as a student handbook or exam policy."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    title = models.CharField(max_length=255)
    file = models.FileField(
        upload_to="documents/%Y/%m/",
        validators=[FileExtensionValidator(["pdf"]), validate_pdf],
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        editable=False,
    )
    error_message = models.TextField(blank=True, editable=False)
    page_count = models.PositiveIntegerField(null=True, blank=True, editable=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.title
