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

## Step 2: Extract text page by page

**What the pieces do**

- `Page` in `documents/models.py` stores one page's text and number. The
  `ForeignKey` links many pages to one document, and `related_name="pages"` is
  what makes `document.pages.all()` work. The `UniqueConstraint` makes the
  database itself refuse two copies of page 5.
- `documents/services.py` holds the processing logic. It stays out of the admin
  so that the background jobs in step 5 can call the same function.
- `transaction.atomic()` makes deleting the old pages and saving the new ones a
  single all-or-nothing change.
- `ExtractionError` separates problems staff can act on, such as a damaged PDF,
  from unexpected bugs. Bugs are logged, and staff see a general message.
- `make_sample_handbook` is a management command: your own `manage.py` command.

**Known limits:** scanned PDFs fail with a clear message because they contain
images, not text. Text in tables and multi-column pages may come out in an odd
order.

**Run it**

```bash
source .venv/bin/activate
python manage.py migrate
python manage.py test
python manage.py runserver
```

In the admin, upload `samples/sample_handbook.pdf`. The status should become
**Ready**, and the document's page should list the text of all 6 pages.

**Try this:** in `python manage.py shell`, run:

```python
from documents.models import Document
document = Document.objects.first()
document.pages.get(number=4).text
```

You should see the grading rules on page 4.

## Step 3: Split pages into chunks

**What the pieces do**

- `documents/chunking.py` holds plain Python with no database code, so it is
  quick to test. Each chunk has at most 900 characters.
- Neighbouring chunks share up to 150 characters, so a rule near a boundary is
  still found.
- Chunks never cross a page boundary. That is what keeps every citation exact.
- The nearest heading is stored as `section` and later added to the search text,
  so a chunk saying "at least 75 percent" still connects to "Attendance".

**Try this:** change `MAX_CHUNK_CHARS` to 200 and run `python manage.py test`.
Read which tests fail and why, then change it back.

## Step 4: Create and store embeddings

**What the pieces do**

- `documents/embeddings.py` runs `multilingual-e5-small` on your own computer. It
  is free, and uploaded documents never leave the machine for this step. The
  first use downloads the model (a few hundred MB).
- `VectorField(dimensions=384)` stores one embedding per chunk. The dimension
  must match the model exactly.
- `HnswIndex` is like a book's index for meanings. Without it, every search
  would compare the question against every chunk.
- Embedding happens before `transaction.atomic()` because a database transaction
  should not stay open during slow work.

Documents processed before this step have no embeddings. Select them in the
admin and run **Process selected documents again**.

## Step 5: Process uploads in the background

Embedding can take minutes, and nobody should wait on a loading page that long.
Uploading now only saves the file. A separate process does the work:

```bash
python manage.py runserver     # terminal 1
python manage.py run_worker    # terminal 2
```

**What the pieces do**

- The database is the queue: `status="pending"` means "waiting". This project
  does not use Celery because that needs a separate broker such as Redis, and
  PostgreSQL can do this job well at this size.
- `select_for_update(skip_locked=True)` in `claim_next_document` stops two
  workers from taking the same document.
- `processing_started_at` and `attempts` handle crashes. A document stuck for 15
  minutes is retried, and after 3 attempts it is marked failed.
- `_still_claimed` handles a file being replaced during processing, so old
  results cannot overwrite the newer upload.

**Try this:** upload a PDF with the worker stopped and watch it stay **Pending**.
Then start the worker and refresh.

## Step 6: Combined search

Search runs two ways and merges the results.

- **Vector search** in `_vector_ranking` finds similar meaning, even in another
  language.
- **Keyword search** in `_keyword_ranking` finds exact terms such as "XJ-42".
  `GeneratedField` makes PostgreSQL maintain the `search_vector` column itself.
- **`_fuse`** uses Reciprocal Rank Fusion. The two methods produce incomparable
  scores, so it combines positions in each list instead.

**Try this:** in `python manage.py shell`, with a document processed:

```python
from documents.search import search_chunks
for c in search_chunks("How many classes can I skip?"):
    print(c.page_number, c.text[:60])
```

## Step 7: Measure retrieval quality

`samples/eval_questions.json` holds test questions and the page that answers each
one. Upload `samples/sample_handbook.pdf` with the title `Sample Handbook`, then:

```bash
python manage.py evaluate_retrieval
```

- **Hit rate in top 5:** how often the right page is among the first 5 results.
- **Mean reciprocal rank:** 1.0 means the right page always came first.

Result on the sample: 100% hit rate, 0.84 mean reciprocal rank, and 72% with the
right page first. The sample has only 6 chunks, so the top-5 figure is easy to
reach. Write 30 to 50 questions for your real handbook before trusting a score.

## Step 8: Generate answers with citations

**Setup:** add `ANTHROPIC_API_KEY=...` to `.env`. Each question costs a small amount.

**What the pieces do**

- `assistant/llm.py` is the only file that talks to the model. To change
  provider, change this file.
- `GeneratedAnswer` is a schema. The API returns exactly `found`, `answer` and
  `citations`, so nothing has to be parsed out of free text.
- The model cites passage numbers, never page numbers. Our code converts them
  to pages, so the model cannot invent a page.
- `find_answer` refuses to show an answer without a valid citation.
- `Citation` copies the title, page and excerpt, because chunks are replaced
  whenever a document is processed again.
- Each question stands alone. Follow-up questions do not remember earlier ones.

**Try this:** `python manage.py evaluate_answers` checks answers, page citations
and refusals on the sample. It makes 21 paid API calls.

## Step 9: Roles, collections and versions

- A **Collection** groups documents with one audience. An empty `allowed_groups`
  means every signed-in user can see it. Otherwise only those groups can.
- **Roles:** staff use the admin (`is_staff`). Students are ordinary users, and
  Django **Groups** decide which restricted collections they can read.
- `visible_to` is a custom `QuerySet` method, so access rules live in one place.
- **Replacing a document:** upload the new PDF and set **Replaces** to the old
  one. `searchable_chunks` drops the old version only when the new one is
  `ready`, so there is no gap, and deleting the new one restores the old one.
  This is worked out by a query, so no extra flag can get out of sync.
