import logging
import time

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from assistant.telegram import POLL_SECONDS, call_api, handle_update

logger = logging.getLogger(__name__)
RETRY_SECONDS = 5


class Command(BaseCommand):
    help = "Run the Telegram bot."

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError("Set TELEGRAM_BOT_TOKEN in .env first.")

        self.stdout.write("Bot started. Press Ctrl+C to stop.")
        offset = None
        try:
            while True:
                close_old_connections()
                try:
                    updates = call_api("getUpdates", offset=offset, timeout=POLL_SECONDS)
                except httpx.HTTPError:
                    logger.exception("Could not reach Telegram")
                    time.sleep(RETRY_SECONDS)
                    continue

                for update in updates:
                    # Moving past it first means a bad message cannot jam the bot.
                    offset = update["update_id"] + 1
                    try:
                        handle_update(update)
                    except Exception:
                        logger.exception("Could not answer update %s", update["update_id"])
        except KeyboardInterrupt:
            self.stdout.write("Bot stopped.")
