# Build guide

The goal: students ask questions in plain language and get answers taken from
official university documents, with a link to the exact page.

Every answer travels this path:

```
INDEXING (once per document)
PDF -> text per page -> small chunks -> embeddings -> PostgreSQL

ANSWERING (every question)
question -> find the best chunks -> send them to the LLM -> answer + page citations
```

## Key ideas

- **Chunk:** a small passage of a document. We search chunks because sending
  a whole document for every question is slow and expensive, and irrelevant
  text makes answers worse.
- **Embedding:** a list of numbers representing a text's meaning. Texts with
  similar meanings get similar numbers, so "How many classes can I skip?" can
  match a passage about "absences".
- **pgvector:** a PostgreSQL extension that stores embeddings and finds the
  closest ones.
- **Keyword search:** finds exact terms such as "Article 4.2", which embeddings
  often miss. We combine both kinds of search.
- **Grounding:** telling the LLM to answer only from the supplied passages, and
  to say "not found" when they do not contain the answer.

## Steps

Each step gets its own branch.

| # | Step | Branch | You will learn |
|---|------|--------|----------------|
| 1 | Foundation: project, Postgres, `Document`, admin upload | `feature/project-setup` | Settings, models, migrations, validators, admin |
| 2 | Extract text page by page | `feature/pdf-extraction` | Related models, services, transactions |
| 3 | Split pages into chunks | `feature/chunking` | Keeping page numbers on every chunk |
| 4 | Create and store embeddings | `feature/embeddings` | `VectorField`, indexes |
| 5 | Process uploads in the background | `feature/background-jobs` | Task queues, status updates, retries |
| 6 | Combined search | `feature/hybrid-search` | Full-text search, vector search, merging results |
| 7 | Measure retrieval quality | `feature/retrieval-eval` | Management commands, test questions, scores |
| 8 | Generate answers with citations | `feature/answers` | Prompts, grounding, "not found" handling |
| 9 | Roles, collections, versioning | `feature/collections-versions` | Permissions, replacing old documents |
| 10 | Student chat with source links | `feature/student-chat` | Views, templates or DRF |
| 11 | Staff insights and Telegram bot | `feature/insights` | Aggregations, integrations |

## Step 1: Foundation

**What the pieces do**

- `config/settings.py` reads secrets from `.env`, so they never reach git.
- `documents/models.py` defines `Document`. Its `status` will show progress
  through indexing.
- `documents/validators.py` checks the file's actual bytes, because anyone can
  rename a file to `.pdf`.
- `documents/migrations/0002_enable_pgvector.py` turns on the extension that
  step 4 needs.

**Run it**

```bash
source .venv/bin/activate
python manage.py migrate
python manage.py test
python manage.py createsuperuser
python manage.py runserver
```

Open <http://127.0.0.1:8000/admin/> and upload a PDF under **Documents**.

**Try this:** rename a `.txt` file to `.pdf` and upload it. Django should reject
it, and you can trace that error back to `validate_pdf`.
