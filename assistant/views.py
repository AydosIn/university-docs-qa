from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone

from documents.models import Collection
from documents.search import chunks_in

from .forms import AskForm
from .models import Question
from .services import answer_question

HISTORY_LENGTH = 20


def _limit_reached(user):
    since = timezone.now() - timedelta(hours=1)
    asked = Question.objects.filter(user=user, created_at__gte=since).count()
    return asked >= settings.QUESTIONS_PER_HOUR


@login_required
def ask(request):
    if request.method == "POST":
        form = AskForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Write a question of up to 500 characters.")
        elif _limit_reached(request.user):
            messages.error(
                request,
                f"You have reached the limit of {settings.QUESTIONS_PER_HOUR} questions "
                "an hour. Ask again later.",
            )
        else:
            collections = Collection.objects.visible_to(request.user)
            answer_question(
                form.cleaned_data["text"],
                chunks=chunks_in(collections),
                user=request.user,
            )
        # Redirecting stops a browser refresh from asking the question twice.
        return redirect("ask")

    questions = request.user.questions.prefetch_related("citations")[:HISTORY_LENGTH]
    return render(request, "assistant/ask.html", {"questions": reversed(list(questions))})
