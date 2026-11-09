"""Document processing. Admin pages and, later, background jobs call this code."""

import logging

import pypdfium2 as pdfium
from django.db import transaction

from .chunking import build_chunks
from .embeddings import embed_passages
from .models import Chunk, Document, Page

logger = logging.getLogger(__name__)


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


def process_document(document):
    """Extract a document's pages and record the result in its status."""
    document.status = Document.Status.PROCESSING
    document.error_message = ""
    document.save(update_fields=["status", "error_message"])

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
    # Pages from an earlier version must not be used to answer questions.
    with transaction.atomic():
        document.pages.all().delete()
        document.chunks.all().delete()
        document.status = Document.Status.FAILED
        document.error_message = message
        document.page_count = None
        document.save(update_fields=["status", "error_message", "page_count"])
