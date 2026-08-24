# Strata - Document Analysis

Strata analyzes documents you upload. Nothing is fetched from the web: files go
in, a local LLM reads them, and the dashboard reports what people are saying,
which topics repeat, and what competitors are up to.

It is a fork of Strata Media (a crawler-fed media-intelligence product) with the
entire online tier removed - no scraper, no sources, no scheduled crawls - and
`ollama` as the default LLM provider, so the documents being analyzed never
leave the operator's machine.

## Pipeline

- `backend/services/documents/` - extracts text from an uploaded file (text
  layer where the file has one, OCR where it doesn't)
- `backend/services/projects/project_document_articles.py` - splits a
  document's text into reviewable article candidates
- `backend/analysis/` - the AI stage pipeline (language, sentiment,
  classification, structured extraction, entities)
- `backend/services/pipeline/pipeline.py` - runs that analysis over a project's
  articles as a tracked *analysis run*
- `backend/services/articles/store.py` - Postgres upsert layer
- `backend/main.py` - FastAPI API for auth, projects, articles, analysis runs, chat
- `dashboard/` - React + Vite dashboard

## How content gets in

1. **Upload** - a project (Opinion Monitor) or a study (Competitor Analysis)
   takes files: pdf, doc/docx, xls/xlsx, csv, png/jpg. Each is saved and
   extracted in the background; a scanned PDF falls through to OCR.
2. **Split** - the LLM splits each document's text into discrete article
   candidates. A survey export holds many respondents; a report covers several
   distinct mentions. Each becomes its own reviewable item.
3. **Review** - you approve or reject each candidate. Approving materializes it
   into the `articles` table and queues its analysis.
4. **Analyze** - the AI stage pipeline runs over it: sentiment, tone, topics,
   demographics, entities, structured feedback.

A JSONL import (`Articles → Import`) is the other way in, for moving data
between deployments or bringing in an export from elsewhere.

## Analysis runs

An analysis run is this product's unit of work, replacing the crawler's scrape
run. It re-executes the AI stage pipeline over a project's articles and records
progress as it goes, so **Analysis Runs** in the dashboard shows live counts,
per-document results, and a stop button.

Start one from the **Analysis Runs** page (pick a project and a scope) or from a
project's detail page. Scope is either:

- **Not yet analyzed** - only articles whose analysis has not succeeded, so a
  re-run after a model outage costs exactly what the outage cost.
- **Everything** - re-analyze the whole project, which is what you want after
  switching to a different local model.

Runs stamp the articles they analyze (`articles.pipeline_run_id`), which is what
lets Dashboard, Reports and Competitor Analysis scope to one specific run
instead of a date window.

There is no scheduler: runs are started deliberately.

## LLM provider

Set `LLM_PROVIDER` in `backend/.env`:

- `ollama` (default) - a model on your own hardware, no API key or internet
  access needed. Point `OLLAMA_CHAT_BASE_URL` at wherever it runs;
  `OLLAMA_CHAT_MODEL` picks the model (default `llama3.1`).
- `openai` - OpenAI's Responses API. Requires `OPENAI_API_KEY`.
- `deepseek` - DeepSeek's OpenAI-compatible chat-completions API. Requires
  `DEEPSEEK_API_KEY`.

All provider selection and request formatting lives in `backend/llm_client.py`;
feature modules just call `chat_completion(...)` and never know which provider
is active. Switching to a hosted provider means the uploaded documents are sent
to that provider - a deliberate choice, not a default.

`COMPETITOR_ANALYSIS_LLM_PROVIDER` scopes a different provider to just
`backend/services/competitors/` (document splitting, competitor naming, finding
generation) - e.g. a larger local model for the long reasoning that finding
generation does, while everything else uses a faster one.

Sentiment and classification are separate Hugging Face models, not the LLM.
They run in-process by default (`SENTIMENT_CLASSIFIER_PROVIDER=local`,
`CLASSIFICATION_PROVIDER=local`); setting either to `hf_api` sends that text to
Hugging Face's hosted inference instead.

### Ollama: model resource requirements

Commonly published sizes for each model's default (Q4_K_M-quantized) Ollama tag
- not measured on this repo's own hardware. "Min RAM" is CPU-only inference;
GPU VRAM is only needed for GPU acceleration (recommended - see below).

| Model (`OLLAMA_CHAT_MODEL`) | Params | Download size | Min RAM (CPU) | Recommended VRAM (GPU) |
|---|---|---|---|---|
| `llama3.2:1b` | 1B | ~1.3 GB | ~2 GB | ~2 GB |
| `llama3.2:3b` | 3B | ~2 GB | ~4 GB | ~4 GB |
| `llama3.1:8b` (default) | 8B | ~4.7 GB | ~8 GB | ~6-8 GB |
| `mistral:7b` | 7B | ~4.1 GB | ~8 GB | ~6 GB |
| `qwen2.5:14b` | 14B | ~9 GB | ~16 GB | ~10-12 GB |
| `gemma2:27b` | 27B | ~16 GB | ~32 GB | ~20 GB |
| `mixtral:8x7b` | 47B (13B active) | ~26 GB | ~32 GB+ | ~24 GB |
| `llama3.1:70b` | 70B | ~40 GB | ~64 GB+ | ~48 GB (or multi-GPU) |

Rule of thumb: budget roughly the download size in RAM/VRAM just to load the
model, plus headroom for context - `ollama` has no graceful "not enough memory"
path beyond an OOM kill.

### What local inference costs in wall-clock time

The heaviest calls - splitting a document into candidates, naming competitors
from evidence, writing an analysis card - request up to 1,600-3,000 output
tokens each and are given 90-120s timeouts (`chat_completion(..., timeout=...)`).

| Setup | Typical throughput | Time for a ~2,000-token reply |
|---|---|---|
| Ollama, consumer GPU (8-24 GB VRAM), 7-8B model | ~40-100+ tok/s | ~20-50s |
| Ollama, CPU-only, 7-8B model | ~5-20 tok/s | ~2-7 minutes |
| Ollama, CPU-only, 13B+ model | ~1-8 tok/s | ~4-30+ minutes |
| Hosted (OpenAI/DeepSeek) | tens-to-100+ tok/s | ~3-10s incl. network |

These are widely-cited hardware expectations, not a benchmark of this repo. The
practical reading: a GPU makes local inference comparable to a hosted API, and
CPU-only inference on an 8B model is usable but slow enough that
`LLM_REQUEST_TIMEOUT_SECONDS` may need raising. `ANALYSIS_CONCURRENCY` (default
2) is deliberately low for the same reason - every worker competes for the same
GPU as the local embedding model.

## Clone And Run

### 1. Prepare the backend environment

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
cp .env.example .env
```

Fill in `DATABASE_URL`. With the default `LLM_PROVIDER=ollama` no API key is
needed - just make sure `ollama serve` is running and the model in
`OLLAMA_CHAT_MODEL` has been pulled (`ollama pull llama3.1`).

OCR needs the `tesseract` binary on PATH (the Docker image installs it).

### 2. Run the backend

```bash
uvicorn main:app --port 8000
```

Migrations run on startup (`MIGRATE_ON_STARTUP=false` to manage them out of
band), and the bootstrap admin is created if the `users` table is empty.

### 3. Run the dashboard

```bash
cd dashboard
npm install
npm run dev       # expects the backend at http://localhost:8000
npm run build
npm run lint
```

Override the backend URL with `VITE_API_TARGET` if it isn't on port 8000.

### 4. Tests

```bash
cd backend
python -m pytest tests -q
```

## Docker Deployment

```bash
docker compose up --build
```

- `db` runs PostgreSQL 16
- `backend` runs the FastAPI API
- `frontend` builds the React dashboard
- `nginx` exposes the public app on port 8210
- `adminer` provides a database UI on port 8082
- `ollama` runs the local LLM, with a one-shot `ollama-pull` job that fetches
  `OLLAMA_CHAT_MODEL` once the server is healthy

Set `OLLAMA_CHAT_BASE_URL=http://ollama:11434/v1/chat/completions` in
`backend/.env` so the backend reaches the `ollama` container rather than
itself. After changing the model:

```bash
docker compose up ollama-pull
```

### What runs where

- Public app: `http://localhost:8210/`
- Adminer: `http://localhost:8082/` (System `PostgreSQL`, Server `db`, user /
  password / database all `strata`)
- Backend API: proxied through nginx at `/api`
- Database: `db:5432` inside the Docker network

### Stop the stack

```bash
docker compose down      # keep data
docker compose down -v   # drop the Postgres volume too
```

## Schema migrations

Applied by `backend/migrate.py`, automatically on API startup.

```bash
# from backend/
python migrate.py            # apply anything pending
python migrate.py --status   # show applied vs pending, change nothing
python migrate.py --verify   # exit non-zero if pending or drifted (for CI)
```

- `schema.sql` is version `0001_baseline`. It is idempotent, so re-running it is
  how an existing database converges with a fresh one. It is also mounted into
  `docker-entrypoint-initdb.d`, so a brand-new volume starts from it directly.
- `backend/migrations/NNNN_name.sql` are the forward migrations, applied in
  numeric order, each in its own transaction. That directory is currently empty:
  everything through `0028` was folded back into the baseline once the fork had
  no database left to preserve, so the next one starts at `0002`. See
  `backend/migrations/README.md`.
- Applied versions and their checksums are recorded in `schema_migrations`.
  Editing a migration after it has been applied is a hard error - the runner
  refuses rather than letting environments diverge silently. Add a new
  migration instead.

`schema.sql` is organized in numbered sections (helpers, access control,
projects, analysis runs, articles, per-article output, idea clusters, documents,
competitor study, seed data) with the conventions it follows stated at the top -
identity keys, cascade-vs-set-null, `created_at`/`updated_at` handling, and the
rule that every foreign key has an index that can serve it.

One thing the baseline cannot do on its own: because it is built from
`create table if not exists`, re-applying it to a database that already has a
table leaves that table's existing shape alone. It adds what is missing (new
tables, new indexes) but will not retighten a column or drop a policy. A
database created before the squash therefore keeps its nullable `created_at`
columns and its dormant RLS policies. To land the schema exactly as written,
start from an empty volume:

```bash
docker compose down -v && docker compose up --build
```

Anything that has to reach an existing database belongs in a migration, not in
an edit to the baseline.

## The signal layer

Two derived columns are populated as articles are stored, with no model calls:

- **dates** - parses the free-text `articles.published` into `published_at` plus
  a `published_precision` of `exact`, `day`, or `unknown`. Rows whose date
  cannot be recovered keep a null `published_at` and are excluded from time
  series rather than falling back to `created_at`, which would report when the
  document was uploaded rather than when the thing happened.
- **stories** - groups near-identical bodies into `story_groups` so prevalence
  is counted per independent story instead of per row. That matters most for
  imported data, where one wire story republished by thirty outlets should count
  once.

## Authentication & Roles

The dashboard and API require a logged-in session (cookie-based, not tokens in
localStorage). The first admin is created on backend startup from
`ADMIN_BOOTSTRAP_USERNAME` / `ADMIN_BOOTSTRAP_EMAIL` /
`ADMIN_BOOTSTRAP_PASSWORD` in `backend/.env`, but only if the `users` table is
still empty - it will not touch an existing account. Log in with either the
username or the email.

Every authenticated user can view the dashboard, articles, projects, analysis
runs, and the Intelligence Copilot chat. Roles add write/action permissions on
top of that shared read access (`admin` automatically satisfies every check
below; `viewer`/`editor`/`operator` are independent, not a ladder):

- **viewer** - read-only.
- **editor** - create, update, and delete projects and their documents; use the
  AI metadata suggestions.
- **operator** - start and stop analysis runs, import articles, and delete all
  stored articles.
- **admin** - everything above, plus user management (`/admin/users`) and role
  management (`/admin/roles`).

Role administration is gated by granular permissions rather than one combined
"manage roles" permission: `roles.view`, `roles.create`, `roles.update`,
`roles.delete` (blocked for the system `admin` role and for any role still
assigned to a user). User administration likewise has `users.view`,
`users.create`, `users.update`, `users.delete`. Deleting a user removes their
account and any active sessions; a user can never delete their own account.

Project visibility is per-user: **Admin → Project Access** links dashboard users
to the projects they can see. Admins see every project.

## Deployment Notes

- PostgreSQL must be reachable by the backend container.
- `backend/.env` needs `DATABASE_URL`, and - only if you moved off the local
  default - the active LLM provider's credentials.
- If the backend is deployed separately from the dashboard, keep the API base
  URL consistent with the frontend's `VITE_API_TARGET`.
- Uploaded documents live under `storage/` (bind-mounted into the backend
  container), so that path needs to persist alongside the database.
