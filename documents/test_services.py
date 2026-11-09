import tempfile
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from fpdf import FPDF

from .embeddings import EMBEDDING_DIMENSIONS
from .models import Document
from .services import (
    MAX_ATTEMPTS,
    STALE_AFTER,
    ExtractionError,
    claim_next_document,
    clean_text,
    extract_pages,
    process_document,
    requeue,
)


def fake_embed_passages(texts):
    """Stands in for the real model, which is too slow for unit tests."""
    return [[1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1) for _ in texts]


def make_pdf(*page_texts):
    """Build a real PDF. An empty string makes a blank page."""
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for text in page_texts:
        pdf.add_page()
        if text:
            pdf.cell(text=text)
    return bytes(pdf.output())


def make_document(pdf_bytes, title="Handbook"):
    document = Document(title=title)
    document.file.save("handbook.pdf", ContentFile(pdf_bytes))
    return document


def process_next():
    """Do what the worker does once, and return the fresh document."""
    document = claim_next_document()
    process_document(document)
    document.refresh_from_db()
    return document


class CleanTextTests(SimpleTestCase):
    def test_removes_nul_characters_and_normalizes_line_endings(self):
        self.assertEqual(clean_text(" a\x00b\r\nc\rd "), "ab\nc\nd")


class ExtractPagesTests(SimpleTestCase):
    def test_keeps_pages_in_order(self):
        texts = extract_pages(make_pdf("First page", "Second page"))
        self.assertEqual(texts, ["First page", "Second page"])

    def test_keeps_position_of_blank_pages(self):
        texts = extract_pages(make_pdf("First", "", "Third"))
        self.assertEqual(texts, ["First", "", "Third"])

    def test_damaged_pdf_raises_readable_error(self):
        with self.assertRaisesMessage(ExtractionError, "could not be opened"):
            extract_pages(b"%PDF-1.7 not really a pdf")

    def test_pdf_without_text_raises_readable_error(self):
        with self.assertRaisesMessage(ExtractionError, "No text was found"):
            extract_pages(make_pdf("", ""))


@patch("documents.services.embed_passages", fake_embed_passages)
@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ProcessDocumentTests(TestCase):
    def test_success_stores_numbered_pages(self):
        document = make_document(make_pdf("First", "Second"))

        document = process_next()

        self.assertEqual(document.status, Document.Status.READY)
        self.assertEqual(document.page_count, 2)
        self.assertEqual(
            list(document.pages.values_list("number", "text")),
            [(1, "First"), (2, "Second")],
        )

    def test_success_stores_chunks_with_page_numbers(self):
        make_document(make_pdf("First", "Second"))

        document = process_next()

        self.assertEqual(
            list(document.chunks.values_list("position", "page_number", "text")),
            [(0, 1, "First"), (1, 2, "Second")],
        )

    def test_chunks_store_embeddings(self):
        make_document(make_pdf("First"))

        document = process_next()

        self.assertEqual(len(document.chunks.get().embedding), EMBEDDING_DIMENSIONS)

    def test_processing_twice_does_not_duplicate_pages_or_chunks(self):
        make_document(make_pdf("First", "Second"))
        process_next()
        requeue(Document.objects.all())

        document = process_next()

        self.assertEqual(document.pages.count(), 2)
        self.assertEqual(document.chunks.count(), 2)

    def test_failure_records_message_and_removes_old_pages(self):
        document = make_document(make_pdf("Old text"))
        process_next()
        document.refresh_from_db()
        document.file.save("broken.pdf", ContentFile(b"%PDF-1.7 broken"))
        requeue(Document.objects.all())

        document = process_next()

        self.assertEqual(document.status, Document.Status.FAILED)
        self.assertIn("could not be opened", document.error_message)
        self.assertIsNone(document.page_count)
        self.assertEqual(document.pages.count(), 0)
        self.assertEqual(document.chunks.count(), 0)

    def test_results_are_discarded_if_document_was_queued_again_meanwhile(self):
        make_document(make_pdf("Old file"))
        claimed = claim_next_document()
        requeue(Document.objects.all())

        process_document(claimed)

        claimed.refresh_from_db()
        self.assertEqual(claimed.status, Document.Status.PENDING)
        self.assertEqual(claimed.pages.count(), 0)

    def test_unexpected_error_hides_details_from_staff(self):
        make_document(make_pdf("Text"))

        with patch("documents.services.embed_passages", side_effect=RuntimeError("secret")):
            with self.assertLogs("documents.services", level="ERROR"):
                document = process_next()

        self.assertEqual(document.status, Document.Status.FAILED)
        self.assertNotIn("secret", document.error_message)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ClaimTests(TestCase):
    def test_returns_none_when_queue_is_empty(self):
        self.assertIsNone(claim_next_document())

    def test_oldest_document_goes_first(self):
        make_document(b"%PDF-", title="First")
        make_document(b"%PDF-", title="Second")
        self.assertEqual(claim_next_document().title, "First")
        self.assertEqual(claim_next_document().title, "Second")

    def test_document_being_processed_is_not_claimed_again(self):
        make_document(b"%PDF-")
        claim_next_document()
        self.assertIsNone(claim_next_document())

    def make_stale(self, attempts):
        document = make_document(b"%PDF-")
        Document.objects.filter(pk=document.pk).update(
            status=Document.Status.PROCESSING,
            attempts=attempts,
            processing_started_at=timezone.now() - STALE_AFTER - timedelta(minutes=1),
        )
        return document

    def test_crashed_document_is_claimed_again(self):
        document = self.make_stale(attempts=1)
        claimed = claim_next_document()
        self.assertEqual(claimed.pk, document.pk)
        self.assertEqual(claimed.attempts, 2)

    def test_document_that_keeps_crashing_is_marked_failed(self):
        document = self.make_stale(attempts=MAX_ATTEMPTS)
        self.assertIsNone(claim_next_document())
        document.refresh_from_db()
        self.assertEqual(document.status, Document.Status.FAILED)


@patch("documents.management.commands.run_worker.close_old_connections")
@patch("documents.services.embed_passages", fake_embed_passages)
@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class WorkerAndAdminTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser("admin", "a@example.com", "pw")
        self.client.force_login(admin)

    def upload(self):
        self.client.post(
            reverse("admin:documents_document_add"),
            {
                "title": "Handbook",
                "file": SimpleUploadedFile("handbook.pdf", make_pdf("Attendance rules")),
                "pages-TOTAL_FORMS": "0",
                "pages-INITIAL_FORMS": "0",
            },
        )
        return Document.objects.get()

    def test_upload_waits_for_the_worker(self, _close):
        self.assertEqual(self.upload().status, Document.Status.PENDING)

    def test_worker_processes_upload_and_admin_shows_text(self, _close):
        document = self.upload()

        call_command("run_worker", "--once", stdout=StringIO())

        document.refresh_from_db()
        self.assertEqual(document.status, Document.Status.READY)
        response = self.client.get(
            reverse("admin:documents_document_change", args=[document.pk])
        )
        self.assertContains(response, "Attendance rules")

    def test_reprocess_action_queues_document(self, _close):
        document = self.upload()
        Document.objects.update(status=Document.Status.FAILED, attempts=2)

        self.client.post(
            reverse("admin:documents_document_changelist"),
            {"action": "reprocess", "_selected_action": [document.pk]},
        )

        document.refresh_from_db()
        self.assertEqual(document.status, Document.Status.PENDING)
        self.assertEqual(document.attempts, 0)
