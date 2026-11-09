import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import Document, get_default_collection
from .validators import MAX_PDF_SIZE_BYTES, validate_pdf


class ValidatePdfTests(SimpleTestCase):
    def test_accepts_pdf_bytes(self):
        validate_pdf(SimpleUploadedFile("a.pdf", b"%PDF-1.7 content"))

    def test_rejects_renamed_non_pdf(self):
        with self.assertRaises(ValidationError):
            validate_pdf(SimpleUploadedFile("fake.pdf", b"just some text"))

    def test_rejects_oversized_file(self):
        big = SimpleUploadedFile("big.pdf", b"%PDF-" + b"0" * MAX_PDF_SIZE_BYTES)
        with self.assertRaises(ValidationError):
            validate_pdf(big)

    def test_file_can_be_read_again_after_validation(self):
        upload = SimpleUploadedFile("a.pdf", b"%PDF-1.7 content")
        validate_pdf(upload)
        self.assertEqual(upload.read(), b"%PDF-1.7 content")


class DocumentModelTests(TestCase):
    def test_new_document_starts_pending(self):
        doc = Document(title="Handbook")
        self.assertEqual(doc.status, Document.Status.PENDING)


class DatabaseTests(TestCase):
    def test_pgvector_extension_is_enabled(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            self.assertIsNotNone(cursor.fetchone())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AdminUploadTests(TestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser("admin", "a@example.com", "pw")
        self.client.force_login(admin)
        self.url = reverse("admin:documents_document_add")

    def upload(self, name, content):
        return self.client.post(
            self.url,
            {
                "title": "Handbook",
                "collection": get_default_collection(),
                "file": SimpleUploadedFile(name, content),
                "pages-TOTAL_FORMS": "0",
                "pages-INITIAL_FORMS": "0",
            },
        )

    def test_real_pdf_is_saved(self):
        response = self.upload("handbook.pdf", b"%PDF-1.7 content")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Document.objects.count(), 1)

    def test_renamed_text_file_is_rejected(self):
        response = self.upload("fake.pdf", b"not a pdf")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not a valid PDF")
        self.assertEqual(Document.objects.count(), 0)
