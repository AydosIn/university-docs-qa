"""Find the chunks most relevant to a question."""

import re
from functools import reduce
from operator import or_

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import connection, transaction
from pgvector.django import CosineDistance

from .embeddings import embed_query
from .models import Chunk, Document

CANDIDATES_PER_METHOD = 30
MAX_KEYWORDS = 30

# The standard constant for Reciprocal Rank Fusion. It stops the very first
# result of one method from outweighing everything else.
RRF_K = 60


def searchable_chunks():
    """Chunks that are allowed to appear in answers."""
    return Chunk.objects.filter(
        document__status=Document.Status.READY,
        embedding__isnull=False,
    )


def _vector_ranking(query, chunks):
    embedding = embed_query(query)
    with transaction.atomic():
        with connection.cursor() as cursor:
            # Keeps the index scanning until enough rows pass the filters.
            cursor.execute("SET LOCAL hnsw.iterative_scan = strict_order")
        return list(
            chunks.annotate(distance=CosineDistance("embedding", embedding))
            .order_by("distance")
            .values_list("pk", flat=True)[:CANDIDATES_PER_METHOD]
        )


def _keyword_ranking(query, chunks):
    words = re.findall(r"\w+", query)[:MAX_KEYWORDS]
    if not words:
        return []
    # A chunk needs only some of the words, unlike a default search,
    # which would require all the words of a full question to appear.
    search_query = reduce(
        or_,
        (SearchQuery(word, config="english", search_type="plain") for word in words),
    )
    return list(
        chunks.filter(search_vector=search_query)
        .annotate(rank=SearchRank("search_vector", search_query))
        .order_by("-rank", "pk")
        .values_list("pk", flat=True)[:CANDIDATES_PER_METHOD]
    )


def _fuse(rankings):
    """Merge rankings using Reciprocal Rank Fusion.

    Each method's scores use different units, so we combine positions instead:
    a chunk scores more for being high on a list and for being on both lists.
    """
    scores = {}
    for ranking in rankings:
        for position, pk in enumerate(ranking, start=1):
            scores[pk] = scores.get(pk, 0) + 1 / (RRF_K + position)
    return scores


def search_chunks(query, limit=8, chunks=None):
    """Return the best chunks for a question, best first."""
    if chunks is None:
        chunks = searchable_chunks()

    scores = _fuse([_vector_ranking(query, chunks), _keyword_ranking(query, chunks)])
    best = sorted(scores, key=scores.get, reverse=True)[:limit]

    found = Chunk.objects.select_related("document").in_bulk(best)
    return [found[pk] for pk in best]
