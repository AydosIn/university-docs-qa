from django.core.exceptions import ValidationError

MAX_PDF_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB
PDF_SIGNATURE = b"%PDF-"


def validate_pdf(file):
    """Reject files that are too large or are not really PDFs.

    A file's extension can be renamed, so we check the bytes at the start of
    the file. Every PDF has the signature "%PDF-" near the beginning.
    """
    if file.size > MAX_PDF_SIZE_BYTES:
        raise ValidationError("The PDF must be 25 MB or smaller.")

    file.seek(0)
    header = file.read(1024)
    file.seek(0)

    if PDF_SIGNATURE not in header:
        raise ValidationError("This file is not a valid PDF.")
