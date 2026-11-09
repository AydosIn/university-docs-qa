import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from fpdf import FPDF

from .embeddings import EMBEDDING_DIMENSIONS
from .models import Document
from .services import ExtractionError, clean_text, extract_pages, process_document


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
    def make_document(self, pdf_bytes):
        document = Document(title="Handbook")
        document.file.save("handbook.pdf", ContentFile(pdf_bytes))
        return document

    def test_success_stores_numbered_pages(self):
        document = self.make_document(make_pdf("First", "Second"))

        process_document(document)

        document.refresh_from_db()
        self.assertEqual(document.status, Document.Status.READY)
        self.assertEqual(document.page_count, 2)
        self.assertEqual(
            list(document.pages.values_list("number", "text")),
            [(1, "First"), (2, "Second")],
        )

    def test_success_stores_chunks_with_page_numbers(self):
        document = self.make_document(make_pdf("First", "Second"))

        process_document(document)

        self.assertEqual(
            list(document.chunks.values_list("position", "page_number", "text")),
            [(0, 1, "First"), (1, 2, "Second")],
        )

    def test_chunks_store_embeddings(self):
        document = self.make_document(make_pdf("First"))

        process_document(document)

        self.assertEqual(len(document.chunks.get().embedding), EMBEDDING_DIMENSIONS)

    def test_processing_twice_does_not_duplicate_pages_or_chunks(self):
        document = self.make_document(make_pdf("First", "Second"))

        process_document(document)
        process_document(document)

        self.assertEqual(document.pages.count(), 2)
        self.assertEqual(document.chunks.count(), 2)

    def test_failure_records_message_and_removes_old_pages(self):
        document = self.make_document(make_pdf("Old text"))
        process_document(document)
        document.file.save("broken.pdf", ContentFile(b"%PDF-1.7 broken"))

        process_document(document)

        document.refresh_from_db()
        self.assertEqual(document.status, Document.Status.FAILED)
        self.assertIn("could not be opened", document.error_message)
        self.assertIsNone(document.page_count)
        self.assertEqual(document.pages.count(), 0)


@patch("documents.services.embed_passages", fake_embed_passages)
@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AdminProcessingTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser("admin", "a@example.com", "pw")
        self.client.force_login(admin)

    def test_upload_extracts_pages_and_detail_page_shows_text(self):
        upload = SimpleUploadedFile("handbook.pdf", make_pdf("Attendance rules"))

        self.client.post(
            reverse("admin:documents_document_add"),
            {
                "title": "Handbook",
                "file": upload,
                "pages-TOTAL_FORMS": "0",
                "pages-INITIAL_FORMS": "0",
            },
        )

        document = Document.objects.get()
        self.assertEqual(document.status, Document.Status.READY)
        response = self.client.get(
            reverse("admin:documents_document_change", args=[document.pk])
        )
        self.assertContains(response, "Attendance rules")
