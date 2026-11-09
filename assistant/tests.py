from unittest.mock import patch

import anthropic
from django.test import SimpleTestCase, TestCase

from documents.models import Chunk, Document

from .llm import GeneratedAnswer, LLMError, _format_passages, generate_answer
from .models import Question
from .services import ERROR_MESSAGE, NOT_FOUND_MESSAGE, answer_question


def make_chunks():
    document = Document.objects.create(title="Handbook", file="h.pdf")
    return [
        Chunk.objects.create(document=document, page_number=4, position=0, text="Pass is 55."),
        Chunk.objects.create(document=document, page_number=7, position=1, text="Other text."),
    ]


class AnswerQuestionTests(TestCase):
    def setUp(self):
        self.chunks = make_chunks()
        patcher = patch("assistant.services.search_chunks", return_value=self.chunks)
        self.search = patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, **answer):
        with patch("assistant.services.generate_answer", return_value=GeneratedAnswer(**answer)):
            return answer_question("What is the pass mark?")

    def test_saves_answer_and_citation(self):
        question = self.ask(found=True, answer="It is 55.", citations=[1])

        self.assertEqual(question.status, Question.Status.ANSWERED)
        self.assertEqual(question.answer, "It is 55.")
        citation = question.citations.get()
        self.assertEqual(citation.document_title, "Handbook")
        self.assertEqual(citation.page_number, 4)
        self.assertEqual(citation.excerpt, "Pass is 55.")

    def test_not_found_has_no_citations(self):
        question = self.ask(found=False, answer="Not covered.", citations=[])

        self.assertEqual(question.status, Question.Status.NOT_FOUND)
        self.assertEqual(question.answer, "Not covered.")
        self.assertEqual(question.citations.count(), 0)

    def test_answer_citing_only_invalid_passages_is_not_shown(self):
        question = self.ask(found=True, answer="Made up.", citations=[9, 0, -1])

        self.assertEqual(question.status, Question.Status.NOT_FOUND)
        self.assertEqual(question.answer, NOT_FOUND_MESSAGE)

    def test_repeated_citations_are_saved_once(self):
        question = self.ask(found=True, answer="It is 55.", citations=[1, 1, 2])

        self.assertEqual(
            list(question.citations.values_list("page_number", flat=True).order_by("page_number")),
            [4, 7],
        )

    def test_model_failure_gives_friendly_error(self):
        with patch("assistant.services.generate_answer", side_effect=LLMError("boom")):
            with self.assertLogs("assistant.services", level="ERROR"):
                question = answer_question("Question?")

        self.assertEqual(question.status, Question.Status.ERROR)
        self.assertEqual(question.answer, ERROR_MESSAGE)

    def test_no_search_results_skips_the_model(self):
        self.search.return_value = []

        with patch("assistant.services.generate_answer") as generate:
            question = answer_question("Question?")

        generate.assert_not_called()
        self.assertEqual(question.status, Question.Status.NOT_FOUND)


class GenerateAnswerTests(TestCase):
    def client_returning(self, **fields):
        client = patch("assistant.llm._get_client").start()
        self.addCleanup(patch.stopall)
        response = client.return_value.beta.messages.parse.return_value
        response.stop_reason = fields.get("stop_reason", "end_turn")
        response.parsed_output = fields.get("parsed_output")
        return client

    def test_returns_parsed_output(self):
        expected = GeneratedAnswer(found=True, answer="55", citations=[1])
        client = self.client_returning(parsed_output=expected)

        self.assertEqual(generate_answer("Pass mark?", make_chunks()), expected)

        sent = client.return_value.beta.messages.parse.call_args.kwargs
        content = sent["messages"][0]["content"]
        self.assertIn("Pass is 55.", content)
        self.assertIn("Pass mark?", content)

    def test_refusal_raises(self):
        self.client_returning(stop_reason="refusal")
        with self.assertRaises(LLMError):
            generate_answer("Question?", make_chunks())

    def test_truncated_output_raises(self):
        self.client_returning(stop_reason="max_tokens", parsed_output=None)
        with self.assertRaises(LLMError):
            generate_answer("Question?", make_chunks())

    def test_api_failure_raises(self):
        client = self.client_returning()
        client.return_value.beta.messages.parse.side_effect = anthropic.APIConnectionError(
            request=None
        )
        with self.assertRaises(LLMError):
            generate_answer("Question?", make_chunks())


class FormatPassagesTests(TestCase):
    def test_includes_number_title_and_page(self):
        text = _format_passages(make_chunks())
        self.assertIn('<passage number="2">', text)
        self.assertIn("Document: Handbook, page 7", text)
