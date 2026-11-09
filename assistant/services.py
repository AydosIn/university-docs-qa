import logging
from dataclasses import dataclass, field

from django.db import transaction

from documents.search import search_chunks

from .llm import LLMError, generate_answer
from .models import Citation, Question

logger = logging.getLogger(__name__)

NOT_FOUND_MESSAGE = (
    "I could not find this in the university documents. "
    "Please contact the Registrar's Office."
)
ERROR_MESSAGE = "Sorry, I could not answer that just now. Please try again in a moment."


@dataclass
class Result:
    status: str
    answer: str
    sources: list = field(default_factory=list)


def find_answer(text, chunks=None):
    """Search the documents and ask the model. Saves nothing."""
    results = search_chunks(text, chunks=chunks)
    if not results:
        return Result(Question.Status.NOT_FOUND, NOT_FOUND_MESSAGE)

    try:
        generated = generate_answer(text, results)
    except LLMError:
        logger.exception("Could not generate an answer")
        return Result(Question.Status.ERROR, ERROR_MESSAGE)

    if not generated.found:
        return Result(Question.Status.NOT_FOUND, generated.answer or NOT_FOUND_MESSAGE)

    # Only numbers matching a passage we really sent can become citations.
    numbers = dict.fromkeys(n for n in generated.citations if 1 <= n <= len(results))
    if not numbers:
        # An answer nobody can check is treated as no answer.
        return Result(Question.Status.NOT_FOUND, NOT_FOUND_MESSAGE)

    return Result(
        Question.Status.ANSWERED,
        generated.answer,
        [results[n - 1] for n in numbers],
    )


@transaction.atomic
def _save(text, result, user, channel, external_user_id):
    question = Question.objects.create(
        user=user,
        channel=channel,
        external_user_id=external_user_id,
        text=text,
        answer=result.answer,
        status=result.status,
    )
    Citation.objects.bulk_create(
        Citation(
            question=question,
            document=chunk.document,
            document_title=chunk.document.title,
            page_number=chunk.page_number,
            excerpt=chunk.text,
        )
        for chunk in result.sources
    )
    return question


def answer_question(
    text,
    chunks=None,
    user=None,
    channel=Question.Channel.WEB,
    external_user_id="",
):
    """Answer a question and record it."""
    return _save(text, find_answer(text, chunks), user, channel, external_user_id)
