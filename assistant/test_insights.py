from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Citation, Question
from .telegram import WELCOME, format_reply, handle_update, reply_to


def ask(text, status=Question.Status.ANSWERED, **fields):
    return Question.objects.create(text=text, answer="Answer", status=status, **fields)


class InsightsTests(TestCase):
    def setUp(self):
        self.url = reverse("insights")
        self.client.force_login(User.objects.create_user("staff", is_staff=True))

    def test_students_cannot_open_it(self):
        self.client.force_login(User.objects.create_user("student"))
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_empty_state(self):
        self.assertContains(self.client.get(self.url), "No questions in the last 30 days")

    def test_counts_by_status(self):
        ask("a")
        ask("b", Question.Status.NOT_FOUND)
        ask("c", Question.Status.ERROR)

        context = self.client.get(self.url).context

        self.assertEqual(
            (context["total"], context["answered"], context["not_found"], context["errors"]),
            (3, 1, 1, 1),
        )

    def test_groups_questions_ignoring_case_and_spaces(self):
        ask("Pass mark?")
        ask("  pass MARK? ")
        ask("Other")

        top = self.client.get(self.url).context["top_questions"]

        self.assertEqual(top[0], {"normalized": "pass mark?", "times": 2})

    def test_lists_unanswered_questions_only(self):
        ask("Parking?", Question.Status.NOT_FOUND)
        ask("Pass mark?")

        unanswered = self.client.get(self.url).context["unanswered"]

        self.assertEqual([row["normalized"] for row in unanswered], ["parking?"])

    def test_ignores_old_questions(self):
        old = ask("Ancient")
        Question.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=31))

        self.assertEqual(self.client.get(self.url).context["total"], 0)


class TelegramTests(TestCase):
    def test_command_gets_welcome_without_using_the_model(self):
        with patch("assistant.telegram.answer_question") as answer:
            self.assertEqual(reply_to("/start", 1), WELCOME)
        answer.assert_not_called()

    def test_reply_names_each_source_page_once(self):
        question = ask("Pass mark?")
        for _ in range(2):
            Citation.objects.create(
                question=question, document_title="Handbook", page_number=4, excerpt="x"
            )

        self.assertEqual(format_reply(question), "Answer\n\nSources:\nHandbook, page 4")

    def test_long_question_is_rejected(self):
        with patch("assistant.telegram.answer_question") as answer:
            self.assertIn("up to", reply_to("x" * 501, 1))
        answer.assert_not_called()

    @override_settings(QUESTIONS_PER_HOUR=1)
    def test_limit_applies_per_chat(self):
        ask("Earlier", channel=Question.Channel.TELEGRAM, external_user_id="1")

        with patch("assistant.telegram.answer_question", return_value=ask("New")) as answer:
            self.assertIn("limit", reply_to("Another?", 1))
            answer.assert_not_called()
            reply_to("Another?", 2)
            answer.assert_called_once()

    def test_only_opted_in_collections_are_searched(self):
        from documents.models import Chunk, Collection, Document

        opted_in = Collection.objects.create(name="Public", telegram_enabled=True)
        private = Collection.objects.create(name="Private")
        for collection in (opted_in, private):
            document = Document.objects.create(
                title=collection.name,
                file="x.pdf",
                collection=collection,
                status=Document.Status.READY,
            )
            Chunk.objects.create(
                document=document, page_number=1, position=0, text="t", embedding=[1.0] * 384
            )

        with patch("assistant.telegram.answer_question", return_value=ask("New")) as answer:
            reply_to("Question?", 1)

        chunks = answer.call_args.kwargs["chunks"]
        self.assertEqual(
            list(chunks.values_list("document__title", flat=True)),
            ["Public"],
        )

    def test_message_without_text_is_ignored(self):
        with patch("assistant.telegram.call_api") as api:
            handle_update({"update_id": 1, "message": {"chat": {"id": 1}, "photo": []}})
        api.assert_not_called()

    def test_message_gets_a_reply(self):
        with patch("assistant.telegram.call_api") as api:
            handle_update({"update_id": 1, "message": {"chat": {"id": 7}, "text": "/start"}})
        api.assert_called_once_with("sendMessage", chat_id=7, text=WELCOME)

    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_bot_needs_a_token(self):
        with self.assertRaises(CommandError):
            call_command("run_telegram_bot")
