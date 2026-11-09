import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from documents.search import search_chunks, searchable_chunks


def score_ranks(ranks, k):
    """Return (hit rate, mean reciprocal rank). A rank of None means not found.

    Hit rate: how often the right page appeared in the top k results.
    Mean reciprocal rank: 1.0 means the right page always came first.
    """
    hits = sum(1 for rank in ranks if rank is not None and rank <= k)
    reciprocal = sum(1 / rank for rank in ranks if rank is not None)
    return hits / len(ranks), reciprocal / len(ranks)


class Command(BaseCommand):
    help = "Measure how often search finds the page that holds the answer."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default=str(Path(settings.BASE_DIR) / "samples" / "eval_questions.json"),
        )
        parser.add_argument("--k", type=int, default=5)
        parser.add_argument("--min-hit-rate", type=float, default=0.9)

    def handle(self, *args, file, k, min_hit_rate, **options):
        data = json.loads(Path(file).read_text(encoding="utf-8"))
        chunks = searchable_chunks().filter(document__title=data["document_title"])
        if not chunks.exists():
            raise CommandError(f'No processed document titled "{data["document_title"]}".')

        ranks = []
        for item in data["answerable"]:
            pages = [c.page_number for c in search_chunks(item["question"], limit=k, chunks=chunks)]
            rank = pages.index(item["page"]) + 1 if item["page"] in pages else None
            ranks.append(rank)
            label = f"rank {rank}" if rank else "MISSED"
            self.stdout.write(f'{label:>8}  page {item["page"]}  {item["question"]}')

        hit_rate, mrr = score_ranks(ranks, k)
        self.stdout.write(f"\nHit rate in top {k}: {hit_rate:.0%}")
        self.stdout.write(f"Mean reciprocal rank: {mrr:.2f}")

        if hit_rate < min_hit_rate:
            raise CommandError(f"Hit rate is below the target of {min_hit_rate:.0%}.")
        self.stdout.write(self.style.SUCCESS("Target met."))
