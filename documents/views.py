from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from .models import Collection, Document


@login_required
def document_file(request, pk):
    """Open a PDF in the browser, for people allowed to see its collection."""
    document = get_object_or_404(
        Document,
        pk=pk,
        collection__in=Collection.objects.visible_to(request.user),
    )
    try:
        file = document.file.open("rb")
    except FileNotFoundError as exc:
        raise Http404("The file is missing.") from exc
    return FileResponse(file, content_type="application/pdf")
