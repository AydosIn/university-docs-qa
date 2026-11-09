import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from assistant.models import Question
from assistant.services import find_answer
from documents.search import searchable_chunks


class Command(BaseCommand):
    help = "Check answers and refusals against the test questions. Uses paid API calls."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default=str(Path(settings.BASE_DIR) / "samples" / "eval_questions.json"),
        )

    def report(self, passed, question, detail):
        self.stdout.write(f'{"pass" if passed else "FAIL"}  {question}  ->  {detail}')
        return passed

    def handle(self, *args, file, **options):
        data = json.loads(Path(file).read_text(encoding="utf-8"))
        chunks = searchable_chunks().filter(document__title=data["document_title"])
        if not chunks.exists():
            raise CommandError(f'No processed document titled "{data["document_title"]}".')

        results = []
        for item in data["answerable"]:
            result = find_answer(item["question"], chunks)
            pages = [source.page_number for source in result.sources]
            passed = result.status == Question.Status.ANSWERED and item["page"] in pages
            results.append(self.report(passed, item["question"], f"pages {pages}: {result.answer}"))

        for question in data["unanswerable"]:
            result = find_answer(question, chunks)
            passed = result.status == Question.Status.NOT_FOUND
            results.append(self.report(passed, question, result.status))

        self.stdout.write(f"\nPassed {sum(results)} of {len(results)}.")
