"""Document processing. The admin queues documents and the worker runs this code."""

import logging
from datetime import timedelta

import pypdfium2 as pdfium
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .chunking import build_chunks
from .embeddings import embed_passages
from .models import Chunk, Document, Page

logger = logging.getLogger(__name__)

# A worker that crashes leaves its document in "processing". After this long,
# another worker may take it over, up to MAX_ATTEMPTS times in total.
STALE_AFTER = timedelta(minutes=15)
MAX_ATTEMPTS = 3


class ExtractionError(Exception):
    """A problem with the PDF, written so that staff can read the message."""


def clean_text(text):
    """Normalize line endings and remove NUL characters.

    PostgreSQL refuses to store NUL characters, and some PDFs contain them.
    """
    return text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()


def extract_pages(pdf_bytes):
    """Return a list with one string per page, in page order."""
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
    except pdfium.PdfiumError as exc:
        raise ExtractionError(
            "This PDF could not be opened. It may be damaged or password-protected."
        ) from exc

    try:
        texts = [clean_text(page.get_textpage().get_text_bounded()) for page in pdf]
    finally:
        pdf.close()

    if not any(texts):
        raise ExtractionError(
            "No text was found in this PDF. It may be a scan, which is not supported yet."
        )
    return texts


def requeue(documents):
    """Send a queryset of documents back to the worker."""
    documents.update(
        status=Document.Status.PENDING,
        error_message="",
        attempts=0,
        processing_started_at=None,
    )


def claim_next_document():
    """Reserve the oldest waiting document for this worker, or return None.

    SKIP LOCKED makes each worker pass over rows another worker is claiming,
    so two workers can never pick up the same document.
    """
    while True:
        stale_before = timezone.now() - STALE_AFTER
        with transaction.atomic():
            document = (
                Document.objects.select_for_update(skip_locked=True)
                .filter(
                    Q(status=Document.Status.PENDING)
                    | Q(
                        status=Document.Status.PROCESSING,
                        processing_started_at__lt=stale_before,
                    )
                )
                .order_by("uploaded_at")
                .first()
            )
            if document is None:
                return None

            if document.attempts >= MAX_ATTEMPTS:
                document.status = Document.Status.FAILED
                document.error_message = "Processing stopped unexpectedly several times."
                document.save(update_fields=["status", "error_message"])
                continue

            document.status = Document.Status.PROCESSING
            document.processing_started_at = timezone.now()
            document.attempts += 1
            document.save(update_fields=["status", "processing_started_at", "attempts"])
            return document


def _still_claimed(document):
    """Lock the row and check that nobody queued or took it during the slow work."""
    current = Document.objects.select_for_update().filter(pk=document.pk).first()
    return (
        current is not None
        and current.status == Document.Status.PROCESSING
        and current.processing_started_at == document.processing_started_at
    )


def process_document(document):
    """Index a document claimed with claim_next_document."""
    try:
        with document.file.open("rb") as file:
            texts = extract_pages(file.read())

        drafts = build_chunks(texts)
        # Slow, so it runs before the transaction opens. The section is
        # included so that a chunk is found by its topic as well as its words.
        embeddings = embed_passages(
            [f"{draft.section}\n{draft.text}".strip() for draft in drafts]
        )

        # All or nothing: readers never see a half-replaced set of pages.
        with transaction.atomic():
            if not _still_claimed(document):
                return
            document.pages.all().delete()
            document.chunks.all().delete()
            Page.objects.bulk_create(
                Page(document=document, number=number, text=text)
                for number, text in enumerate(texts, start=1)
            )
            Chunk.objects.bulk_create(
                Chunk(
                    document=document,
                    page_number=draft.page_number,
                    position=position,
                    section=draft.section[:255],
                    text=draft.text,
                    embedding=embedding,
                )
                for position, (draft, embedding) in enumerate(zip(drafts, embeddings))
            )
            document.status = Document.Status.READY
            document.page_count = len(texts)
            document.save(update_fields=["status", "page_count"])
    except ExtractionError as exc:
        _mark_failed(document, str(exc))
    except Exception:
        logger.exception("Could not process document %s", document.pk)
        _mark_failed(document, "Something went wrong while processing this document.")


def _mark_failed(document, message):
    with transaction.atomic():
        if not _still_claimed(document):
            return
        # Pages from an earlier version must not be used to answer questions.
        document.pages.all().delete()
        document.chunks.all().delete()
        document.status = Document.Status.FAILED
        document.error_message = message
        document.page_count = None
        document.save(update_fields=["status", "error_message", "page_count"])
