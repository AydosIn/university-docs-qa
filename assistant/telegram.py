"""Answer questions sent to a Telegram bot."""

from datetime import timedelta

import httpx
from django.conf import settings
from django.utils import timezone

from documents.models import Collection
from documents.search import chunks_in

from .models import Question
from .services import answer_question

MAX_QUESTION_CHARS = 500
# Telegram rejects messages over 4096 characters.
MAX_ANSWER_CHARS = 3500
POLL_SECONDS = 30

WELCOME = (
    "Ask about the university's rules, such as attendance, exams, grades or "
    "deadlines. Each answer names the page it came from."
)


def call_api(method, **params):
    response = httpx.post(
        f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}",
        json=params,
        timeout=POLL_SECONDS + 10,
    )
    response.raise_for_status()
    return response.json()["result"]


def _limit_reached(chat_id):
    since = timezone.now() - timedelta(hours=1)
    asked = Question.objects.filter(
        channel=Question.Channel.TELEGRAM,
        external_user_id=str(chat_id),
        created_at__gte=since,
    ).count()
    return asked >= settings.QUESTIONS_PER_HOUR


def format_reply(question):
    lines = [question.answer[:MAX_ANSWER_CHARS]]
    sources = [f"{c.document_title}, page {c.page_number}" for c in question.margin_pages()]
    if sources:
        lines += ["", "Sources:", *sources]
    return "\n".join(lines)


def reply_to(text, chat_id):
    """Return the bot's reply to one message."""
    text = text.strip()
    if text.startswith("/"):
        return WELCOME
    if len(text) > MAX_QUESTION_CHARS:
        return f"Write a question of up to {MAX_QUESTION_CHARS} characters."
    if _limit_reached(chat_id):
        return (
            f"You have reached the limit of {settings.QUESTIONS_PER_HOUR} questions "
            "an hour. Ask again later."
        )

    # Telegram users are not signed in, so only opted-in collections are used.
    question = answer_question(
        text,
        chunks=chunks_in(Collection.objects.filter(telegram_enabled=True)),
        channel=Question.Channel.TELEGRAM,
        external_user_id=str(chat_id),
    )
    return format_reply(question)


def handle_update(update):
    message = update.get("message") or {}
    text = message.get("text")
    if not text:
        return
    chat_id = message["chat"]["id"]
    call_api("sendMessage", chat_id=chat_id, text=reply_to(text, chat_id))
