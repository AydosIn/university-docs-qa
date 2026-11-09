import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from documents.services import claim_next_document, process_document

POLL_SECONDS = 3


class Command(BaseCommand):
    help = "Process uploaded documents in the background."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Stop when the queue is empty instead of waiting for more.",
        )

    def handle(self, *args, once, **options):
        self.stdout.write("Worker started. Press Ctrl+C to stop.")
        try:
            while True:
                # A long-running process must drop database connections that died.
                close_old_connections()
                document = claim_next_document()
                if document is None:
                    if once:
                        return
                    time.sleep(POLL_SECONDS)
                    continue

                self.stdout.write(f"Processing: {document.title}")
                process_document(document)
                document.refresh_from_db()
                self.stdout.write(f"Finished with status: {document.status}")
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped.")
