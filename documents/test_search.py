from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from .embeddings import EMBEDDING_DIMENSIONS
from .models import Chunk, Document
from .search import _fuse, search_chunks


def vector(index):
    """A unit vector pointing in its own direction, so distances are predictable."""
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[index] = 1.0
    return values


def make_chunk(document, position, text, embedding):
    return Chunk.objects.create(
        document=document,
        page_number=position + 1,
        position=position,
        text=text,
        embedding=embedding,
    )


class FuseTests(SimpleTestCase):
    def test_item_on_both_lists_beats_item_on_one(self):
        scores = _fuse([[1, 2], [3, 2]])
        self.assertGreater(scores[2], scores[1])
        self.assertGreater(scores[2], scores[3])


class SearchChunksTests(TestCase):
    def setUp(self):
        self.document = Document.objects.create(
            title="Handbook",
            file="handbook.pdf",
            status=Document.Status.READY,
        )

    def search(self, query, query_vector):
        with patch("documents.search.embed_query", return_value=query_vector):
            return search_chunks(query)

    def test_finds_by_meaning_without_shared_words(self):
        meaning = make_chunk(self.document, 0, "Absences are limited.", vector(0))
        make_chunk(self.document, 1, "Grades are published.", vector(1))

        results = self.search("skip class", vector(0))

        self.assertEqual(results[0], meaning)

    def test_finds_exact_terms_the_embedding_misses(self):
        make_chunk(self.document, 0, "General information.", vector(0))
        exact = make_chunk(self.document, 1, "Rule XJ-42 covers appeals.", vector(1))

        results = self.search("XJ-42", vector(0))

        self.assertIn(exact, results)

    def test_keyword_search_matches_word_forms(self):
        chunk = make_chunk(self.document, 0, "Examinations are held in June.", vector(1))
        make_chunk(self.document, 1, "Other text.", vector(0))

        results = self.search("examination", vector(0))

        self.assertEqual(results[0], chunk)

    def test_ignores_documents_that_are_not_ready(self):
        make_chunk(self.document, 0, "Visible.", vector(0))
        hidden_document = Document.objects.create(
            title="Draft",
            file="draft.pdf",
            status=Document.Status.PROCESSING,
        )
        hidden = make_chunk(hidden_document, 0, "Hidden.", vector(0))

        self.assertNotIn(hidden, self.search("Hidden", vector(0)))

    def test_respects_limit(self):
        for position in range(12):
            make_chunk(self.document, position, f"Rule {position}.", vector(position))

        with patch("documents.search.embed_query", return_value=vector(0)):
            self.assertEqual(len(search_chunks("rule", limit=3)), 3)

    def test_question_without_words_still_works(self):
        make_chunk(self.document, 0, "Text.", vector(0))
        self.assertEqual(len(self.search("???", vector(0))), 1)
