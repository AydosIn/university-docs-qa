import tempfile
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from documents.models import Collection, Document

from .models import Citation, Question


def make_question(user, text="Pass mark?", status=Question.Status.ANSWERED):
    return Question.objects.create(user=user, text=text, answer="It is 55.", status=status)


class AskPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("student", password="pw")
        self.client.force_login(self.user)
        self.url = reverse("ask")

    def test_requires_sign_in(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"{reverse('login')}?next=/")

    def test_empty_history_shows_welcome(self):
        self.assertContains(self.client.get(self.url), "Ask about the university")

    def test_shows_only_your_own_questions(self):
        make_question(self.user, "Mine")
        make_question(User.objects.create_user("other"), "Theirs")

        response = self.client.get(self.url)

        self.assertContains(response, "Mine")
        self.assertNotContains(response, "Theirs")

    def test_answer_links_to_cited_page_once(self):
        question = make_question(self.user)
        document = Document.objects.create(title="Handbook", file="h.pdf")
        for excerpt in ["One", "Two"]:
            Citation.objects.create(
                question=question,
                document=document,
                document_title="Handbook",
                page_number=4,
                excerpt=excerpt,
            )

        response = self.client.get(self.url)

        link = f'{reverse("document_file", args=[document.pk])}#page=4'
        self.assertContains(response, link, count=1)
        self.assertContains(response, "<blockquote>One</blockquote>")
        self.assertContains(response, "<blockquote>Two</blockquote>")

    def test_citation_of_deleted_document_has_no_link(self):
        question = make_question(self.user)
        Citation.objects.create(
            question=question, document=None, document_title="Old", page_number=2, excerpt="x"
        )
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_student_text_is_escaped(self):
        make_question(self.user, "<script>alert(1)</script>")
        self.assertNotContains(self.client.get(self.url), "<script>alert(1)")

    def test_posting_asks_within_visible_collections_and_redirects(self):
        with patch("assistant.views.answer_question") as answer:
            response = self.client.post(self.url, {"text": "  Pass mark?  "})

        self.assertRedirects(response, self.url)
        args, kwargs = answer.call_args
        self.assertEqual(args[0], "Pass mark?")
        self.assertEqual(kwargs["user"], self.user)
        self.assertIn("chunks", kwargs)

    def test_blank_question_is_rejected(self):
        with patch("assistant.views.answer_question") as answer:
            response = self.client.post(self.url, {"text": "   "}, follow=True)

        answer.assert_not_called()
        self.assertContains(response, "Write a question")

    @override_settings(QUESTIONS_PER_HOUR=1)
    def test_hourly_limit_blocks_more_questions(self):
        make_question(self.user)

        with patch("assistant.views.answer_question") as answer:
            response = self.client.post(self.url, {"text": "Another?"}, follow=True)

        answer.assert_not_called()
        self.assertContains(response, "limit of 1 questions")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DocumentFileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("student")
        self.group = Group.objects.create(name="Medicine")
        collection = Collection.objects.create(name="Restricted")
        collection.allowed_groups.add(self.group)
        self.document = Document(title="Secret", collection=collection)
        self.document.file.save("secret.pdf", ContentFile(b"%PDF-1.7"))
        self.url = reverse("document_file", args=[self.document.pk])

    def test_anonymous_is_sent_to_sign_in(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_user_outside_group_gets_404(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_group_member_gets_the_pdf(self):
        self.user.groups.add(self.group)
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.7")

    def test_missing_file_gives_404(self):
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.document.file.delete(save=False)
        self.assertEqual(self.client.get(self.url).status_code, 404)


class LoginPageTests(TestCase):
    def test_wrong_password_explains_the_problem(self):
        response = self.client.post(reverse("login"), {"username": "x", "password": "y"})
        self.assertContains(response, "match")

    def test_sign_in_goes_to_ask_page(self):
        User.objects.create_user("student", password="correct-horse")
        response = self.client.post(
            reverse("login"), {"username": "student", "password": "correct-horse"}
        )
        self.assertRedirects(response, reverse("ask"))
