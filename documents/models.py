from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.core.validators import FileExtensionValidator
from django.db import models
from pgvector.django import HnswIndex, VectorField

from .embeddings import EMBEDDING_DIMENSIONS
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
    attempts = models.PositiveSmallIntegerField(default=0, editable=False)
    processing_started_at = models.DateTimeField(null=True, blank=True, editable=False)
    page_count = models.PositiveIntegerField(null=True, blank=True, editable=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.title


class Page(models.Model):
    """The text of one PDF page. Citations depend on its page number."""

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="pages",
    )
    number = models.PositiveIntegerField(help_text="Page number, starting at 1.")
    text = models.TextField(blank=True)

    class Meta:
        ordering = ["document", "number"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "number"],
                name="unique_page_number_per_document",
            ),
        ]

    def __str__(self):
        return f"{self.document} (page {self.number})"


class Chunk(models.Model):
    """A small passage of a page. Search finds chunks, not whole documents."""

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    page_number = models.PositiveIntegerField()
    position = models.PositiveIntegerField(help_text="Order within the document.")
    section = models.CharField(max_length=255, blank=True)
    text = models.TextField()
    embedding = VectorField(dimensions=EMBEDDING_DIMENSIONS, null=True, blank=True)
    # PostgreSQL keeps this column up to date whenever the text changes.
    search_vector = models.GeneratedField(
        expression=SearchVector("text", config="english"),
        output_field=SearchVectorField(),
        db_persist=True,
    )

    class Meta:
        ordering = ["document", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["document", "position"],
                name="unique_chunk_position_per_document",
            ),
        ]
        indexes = [
            GinIndex(name="chunk_search_vector_gin", fields=["search_vector"]),
            # Finds the closest embeddings without comparing against every row.
            HnswIndex(
                name="chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.document} (page {self.page_number}, chunk {self.position})"
