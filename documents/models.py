from django.contrib.auth.models import Group
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from pgvector.django import HnswIndex, VectorField

from .embeddings import EMBEDDING_DIMENSIONS
from .validators import validate_pdf


class CollectionQuerySet(models.QuerySet):
    def visible_to(self, user):
        if user.is_staff:
            return self
        if not user.is_authenticated:
            return self.none()
        return self.filter(
            Q(allowed_groups__isnull=True) | Q(allowed_groups__in=user.groups.all())
        ).distinct()


class Collection(models.Model):
    """A set of documents with the same audience, such as "Medical Faculty"."""

    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)
    allowed_groups = models.ManyToManyField(
        Group,
        blank=True,
        help_text="Leave empty to let every signed-in user see this collection.",
    )
    telegram_enabled = models.BooleanField(
        "available on Telegram",
        default=False,
        help_text="Anyone using the Telegram bot can get answers from this collection.",
    )

    objects = CollectionQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def get_default_collection():
    return Collection.objects.get_or_create(name="General")[0].pk


class Document(models.Model):
    """One uploaded PDF, such as a student handbook or exam policy."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    title = models.CharField(max_length=255)
    collection = models.ForeignKey(
        Collection,
        on_delete=models.PROTECT,
        related_name="documents",
        default=get_default_collection,
    )
    replaces = models.OneToOneField(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replaced_by",
        help_text="The older document this one replaces, once this one is ready.",
    )
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

    def clean(self):
        if self.replaces_id is None:
            return
        if self.replaces_id == self.pk:
            raise ValidationError({"replaces": "A document cannot replace itself."})
        if self.replaces.collection_id != self.collection_id:
            raise ValidationError({"replaces": "Choose a document from the same collection."})


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
