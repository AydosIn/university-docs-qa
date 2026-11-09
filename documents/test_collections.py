from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase

from .embeddings import EMBEDDING_DIMENSIONS
from .models import Chunk, Collection, Document
from .search import chunks_in, search_chunks, searchable_chunks

VECTOR = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


def make_ready_document(title, collection=None, replaces=None, status=Document.Status.READY):
    fields = {"collection": collection} if collection else {}
    document = Document.objects.create(
        title=title, file=f"{title}.pdf", status=status, replaces=replaces, **fields
    )
    Chunk.objects.create(
        document=document, page_number=1, position=0, text=title, embedding=VECTOR
    )
    return document


class VisibilityTests(TestCase):
    def setUp(self):
        self.medicine = Group.objects.create(name="Medicine")
        self.open = Collection.objects.create(name="Open")
        self.restricted = Collection.objects.create(name="Restricted")
        self.restricted.allowed_groups.add(self.medicine)
        self.user = User.objects.create_user("student")

    def visible(self, user):
        return set(Collection.objects.visible_to(user).filter(pk__in=[self.open.pk, self.restricted.pk]))

    def test_anonymous_sees_nothing(self):
        self.assertEqual(self.visible(AnonymousUser()), set())

    def test_user_outside_group_sees_only_open_collections(self):
        self.assertEqual(self.visible(self.user), {self.open})

    def test_group_member_sees_restricted_collection(self):
        self.user.groups.add(self.medicine)
        self.assertEqual(self.visible(self.user), {self.open, self.restricted})

    def test_staff_sees_everything(self):
        staff = User.objects.create_user("staff", is_staff=True)
        self.assertEqual(self.visible(staff), {self.open, self.restricted})

    def test_search_stays_inside_visible_collections(self):
        make_ready_document("open doc", self.open)
        secret = make_ready_document("secret doc", self.restricted)
        allowed = Collection.objects.visible_to(self.user)

        with patch("documents.search.embed_query", return_value=VECTOR):
            results = search_chunks("secret doc", chunks=chunks_in(allowed))

        self.assertNotIn(secret, [chunk.document for chunk in results])
        self.assertEqual(len(results), 1)


class VersioningTests(TestCase):
    def titles(self):
        return set(searchable_chunks().values_list("document__title", flat=True))

    def test_replacement_hides_old_version_once_ready(self):
        old = make_ready_document("2025")
        make_ready_document("2026", replaces=old)
        self.assertEqual(self.titles(), {"2026"})

    def test_old_version_stays_while_replacement_is_processing(self):
        old = make_ready_document("2025")
        make_ready_document("2026", replaces=old, status=Document.Status.PROCESSING)
        self.assertEqual(self.titles(), {"2025"})

    def test_old_version_stays_when_replacement_fails(self):
        old = make_ready_document("2025")
        make_ready_document("2026", replaces=old, status=Document.Status.FAILED)
        self.assertEqual(self.titles(), {"2025"})

    def test_deleting_replacement_restores_old_version(self):
        old = make_ready_document("2025")
        new = make_ready_document("2026", replaces=old)
        new.delete()
        self.assertEqual(self.titles(), {"2025"})

    def test_only_newest_of_a_chain_is_used(self):
        first = make_ready_document("2024")
        second = make_ready_document("2025", replaces=first)
        make_ready_document("2026", replaces=second)
        self.assertEqual(self.titles(), {"2026"})

    def test_cannot_replace_document_in_another_collection(self):
        old = make_ready_document("2025", Collection.objects.create(name="A"))
        new = Document(
            title="2026",
            file="x.pdf",
            collection=Collection.objects.create(name="B"),
            replaces=old,
        )
        with self.assertRaises(ValidationError):
            new.full_clean()

    def test_cannot_replace_itself(self):
        document = make_ready_document("2025")
        document.replaces = document
        with self.assertRaises(ValidationError):
            document.full_clean()
