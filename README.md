# University Docs Q&A

Students ask questions in plain language and get answers taken from official
university documents, each linked to the exact page it came from. If the
documents do not cover a question, the app says so instead of guessing.

Built with Django, PostgreSQL and pgvector. Answers are written by Claude.
Embeddings run locally with a free multilingual model, so questions in Uzbek and
Russian can match English documents.

## What it does

- Staff upload PDFs once, and every student can ask about them.
- Search combines meaning and exact keywords.
- Every answer must cite a page, and citations open the PDF at that page.
- A new version of a document replaces the old one when it finishes processing.
- Collections and groups control who can read what.
- Staff see the most common questions and the ones the documents could not answer.
- Optional Telegram bot.

## Setup

You need Python 3.12, PostgreSQL with pgvector, and an
[Anthropic API key](https://platform.claude.com).

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
createdb university_docs_qa
cp .env.example .env       # then fill in the values
python manage.py migrate
python manage.py createsuperuser
```

## Run

```bash
python manage.py runserver     # the website
python manage.py run_worker    # processes uploaded documents
```

Upload PDFs at <http://127.0.0.1:8000/admin/>, then ask at <http://127.0.0.1:8000/>.

## Check quality

```bash
python manage.py test
python manage.py make_sample_handbook   # recreates samples/sample_handbook.pdf
python manage.py evaluate_retrieval     # free
python manage.py evaluate_answers       # uses paid API calls
```

## Limits

- Scanned PDFs are rejected, because OCR is not built yet.
- Text in complex tables may come out in an odd order.
- Each question stands alone, with no memory of earlier ones.
- This is set up for local development, not production hosting.

[docs/GUIDE.md](docs/GUIDE.md) explains how each part was built.
