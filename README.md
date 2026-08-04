# Strata Media - Source Intelligence

Strata Media ingests content from configured sources, enriches it with AI, stores
it in Supabase, and surfaces it in the dashboard.

## Pipeline

- `backend/scraper/` - Scrapy project for source and page extraction
- `backend/services/articles/enrich.py` - AI enrichment stage
- `backend/services/articles/store.py` - Supabase upsert layer
- `backend/main.py` - FastAPI API for scraping, sources, projects, and chat
- `dashboard/` - React + Vite dashboard

## Stages

1. Scraper - `backend/scraper/spiders/source_rss.py`. Reads sources from
   Supabase `sources` or the `SOURCES` env var override, discovers article links,
   and extracts clean title/date/text with trafilatura.
2. Enricher - `backend/services/articles/enrich.py`. Cleans and tags each
   article with AI, then falls back to neutral defaults if the request fails.
3. Saver - `backend/services/articles/store.py`. Upserts enriched articles
   into Supabase.
4. Dashboard - `dashboard/`. Reads live data from Supabase and calls the
   backend API.

A single configured LLM provider is used everywhere in this app for AI:
article enrichment (`backend/services/articles/enrich.py`), Intelligence
Copilot chat (`backend/main.py`), and hashtag/keyword/username/source
discovery (`backend/services/projects/projects_ai.py` and
`backend/services/projects/project_discovery.py`). All provider
selection and request formatting lives in `backend/llm_client.py`; feature
modules just call `chat_completion(...)` and never know which provider is
active.

### Choosing an LLM provider

Set `LLM_PROVIDER` in `backend/.env` to pick the backend:

- `openai` (default) - uses OpenAI's Responses API. Requires `OPENAI_API_KEY`;
  `OPENAI_CHAT_BASE_URL` and `OPENAI_CHAT_MODEL` are optional overrides
  (default model `gpt-5-nano`).
- `deepseek` - uses DeepSeek's OpenAI-compatible chat-completions API.
  Requires `DEEPSEEK_API_KEY`; `DEEPSEEK_CHAT_BASE_URL` and
  `DEEPSEEK_CHAT_MODEL` are optional overrides (default model
  `deepseek-chat`).

Only the env vars for the selected provider need to be set - switching
providers is a single env var change, no code changes or redeploy of a
different image required. Whichever provider is active, LLM failures surface
the same stable, provider-neutral error codes (`llm_config_error`,
`llm_auth_error`, `llm_rate_limited`, `llm_timeout`, `llm_unavailable`,
`llm_bad_request`, `llm_invalid_response`) to the dashboard - raw provider
errors are never sent to the client.

## Clone And Run

### 1. Clone the repository

```bash
git clone <repo-url>
cd strata-media
```

If you already have the repo locally, pull the latest changes instead:

```bash
git pull
```

### 2. Prepare the backend environment

Copy the example env file and edit the values for your machine:

```bash
cd backend
copy .env.example .env
```

On macOS/Linux, use `cp .env.example .env` instead of `copy`.

Set at minimum:

- `DATABASE_URL`
- An LLM provider's credentials - by default `OPENAI_API_KEY` (OpenAI),
  required for enrichment, Intelligence Copilot chat, and project/source
  discovery. Set `LLM_PROVIDER=deepseek` and `DEEPSEEK_API_KEY` instead to use
  DeepSeek - see [Choosing an LLM provider](#choosing-an-llm-provider).

### 3. Run the backend locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-optional.txt
uvicorn main:app --port 8000
```

If you don't need local embeddings, you can skip the optional requirements
file.

Migrations run automatically on startup (see
[Schema migrations](#schema-migrations)), so a fresh, empty `DATABASE_URL`
gets every table created for you the first time you run `uvicorn`. To apply
them without starting the server - e.g. before seeding - run it directly:

```bash
python migrate.py
```

### 4. Seed example data (optional)

The dashboard is empty until something has scraped or a project has been
analyzed. To have example data to look at right away, run one or both of the
bundled seed scripts from `backend/` (venv active, `DATABASE_URL` set):

```bash
python seed_competitor_demo.py        # fictional "Northwind" competitor study
python seed_strata_create_demo.py     # real strata create study: 10 competitors, 5 AI-generated reports
```

Both talk to the database directly, need no LLM API key, and are safe to
re-run - each resets just its own study. Remove one with `--wipe`:

```bash
python seed_strata_create_demo.py --wipe
```

`seed_strata_create_demo.py` reproduces a real completed run of this
project's own competitor-study pipeline (real competitor names, a real
derived business profile, real AI-written reports), captured directly from
this project's database. It does not reseed the underlying scraped articles
or the "filtered out" evidence trail behind a report, so that panel is empty
for this seeded study - see the module docstring for why.

### 5. Run the dashboard locally

Open a second terminal:

```bash
cd dashboard
npm install
copy .env.example .env
npm run dev
```

On macOS/Linux, use `cp .env.example .env` instead of `copy`.

The dashboard expects the backend on `http://localhost:8000` unless you set
`VITE_API_TARGET`.

### 6. Run the pipeline manually

You can run the scrape/enrich/save flow directly from the backend folder:

```bash
scrapy crawl source_rss -O articles.json
python -m services.articles.enrich
```

## Docker Deployment

This repo includes a full Docker stack:

- `db` runs PostgreSQL 16
- `backend` runs the FastAPI API
- `frontend` builds the React dashboard
- `nginx` exposes the public app on port 80
- `adminer` provides a database UI on port 8080

### Start the stack

```bash
docker compose up --build
```

### What runs where

- Public app: `http://localhost/`
- Adminer: `http://localhost:8080/`
- Backend API: proxied through nginx at `/api` and `/scrape`
- Database: `db:5432` inside the Docker network

### Required Docker env files

The backend container reads `backend/.env`. Make sure it contains values for:

- `DATABASE_URL=postgresql://strata:strata@db:5432/strata`
- Whichever LLM provider is selected via `LLM_PROVIDER` (default `openai`,
  requiring `OPENAI_API_KEY`) - required for enrichment, Intelligence Copilot
  chat, and project/source discovery. See
  [Choosing an LLM provider](#choosing-an-llm-provider).

### Adminer login

Use these values to inspect the local database:

- System: `PostgreSQL`
- Server: `db`
- Username: `strata`
- Password: `strata`
- Database: `strata`

### Stop the stack

```bash
docker compose down
```

To remove the Postgres volume as well:

```bash
docker compose down -v
```

### Schema migrations

Schema changes are applied by `backend/migrate.py`, which runs automatically when
the API starts. Dropping the Postgres volume is no longer needed to pick up a
schema change.

```bash
# from backend/
python migrate.py            # apply anything pending
python migrate.py --status   # show applied vs pending, change nothing
python migrate.py --verify   # exit non-zero if pending or drifted (for CI)
```

How it works:

- `schema.sql` is version `0001_baseline`. It is idempotent, so it is safe to
  re-run, and re-running it is how an existing database converges with a fresh
  one. It is also still mounted into `docker-entrypoint-initdb.d`, so a brand-new
  volume starts from it directly.
- `backend/migrations/NNNN_name.sql` are the forward migrations, applied in
  numeric order, each in its own transaction.
- Applied versions and their checksums are recorded in `schema_migrations`.
  Editing a migration after it has been applied is a hard error — the runner
  refuses rather than letting environments diverge silently. Add a new migration
  instead.

To add one: create `backend/migrations/0004_short_name.sql`, keep every statement
idempotent (`if not exists`, `or replace`, `on conflict do nothing`), and restart
the backend or run `python migrate.py`.

Set `MIGRATE_ON_STARTUP=false` to manage migrations out of band instead — e.g.
when several backend replicas share one database and only the deploy step should
migrate it.

### Backfilling the signal layer

Two derived columns are populated from data already in Postgres — no re-scraping
and no model calls:

```bash
# from backend/
python backfill_signal_layer.py --dry-run    # report only
python backfill_signal_layer.py              # both passes
```

- **dates** — parses the free-text `articles.published` into `published_at` plus
  a `published_precision` of `exact`, `day`, or `unknown`. Rows whose date cannot
  be recovered keep a null `published_at` and must be excluded from time series
  rather than falling back to `created_at`, which would report when we scraped a
  story rather than when it was published.
- **stories** — groups near-identical bodies into `story_groups` so prevalence
  can be counted per independent story instead of per URL. One wire story
  republished by thirty outlets is one story, not thirty sources.

Both passes are batched, committed per batch, and resumable — progress lives in
the data, so an interrupted run is continued by running it again.

### Seeding example data

To load the same bundled example studies into the Docker stack's database,
run the seed scripts inside the running `backend` container:

```bash
docker compose exec backend python seed_competitor_demo.py
docker compose exec backend python seed_strata_create_demo.py
```

See [Seed example data](#4-seed-example-data-optional) above for what each
script creates and how to remove one with `--wipe`.

### Reset the database (fresh start)

To wipe all local data and rebuild from scratch:

```bash
docker compose down -v
docker compose up --build -d
```

The volume is recreated from `schema.sql`, then the backend applies any
migrations on top at startup.

## Deployment Notes

For a production-style deployment, the important pieces are:

- PostgreSQL must be reachable by the backend container
- `backend/.env` must include the database URL and the active LLM provider's
  credentials (`OPENAI_API_KEY` by default, or `LLM_PROVIDER=deepseek` plus
  `DEEPSEEK_API_KEY`)

The current Docker setup is suitable for a single-server deployment where the
database, backend, frontend, and reverse proxy all run together.

If you deploy the backend separately from the dashboard, keep the API base URL
consistent with the frontend's `VITE_API_TARGET` setting.

## Authentication & Roles

The dashboard and API require a logged-in session (cookie-based, not tokens
in localStorage). The first admin is created on backend startup from
`ADMIN_BOOTSTRAP_USERNAME` / `ADMIN_BOOTSTRAP_EMAIL` / `ADMIN_BOOTSTRAP_PASSWORD`
in `backend/.env`, but only if the `users` table is still empty - it will not
touch an existing account. Log in with either the username or the email.

Every authenticated user, regardless of role, can view the dashboard, articles,
sources, projects, pipeline runs, and the Intelligence Copilot chat. Roles add
specific write/action permissions on top of that shared read access (`admin` is
the only role that automatically satisfies every check below -
`viewer`/`editor`/`operator` are otherwise independent, not a ladder):

- **viewer** - read-only. No create, update, delete, or pipeline actions.
- **editor** - create, update, and delete sources and projects; link sources to
  projects; use AI project discovery/suggestions.
- **operator** - trigger scrapes (`POST /scrape`), stop pipeline runs, and
  delete all stored articles.
- **admin** - everything above, plus user management: create, delete, change
  roles for, and enable/disable users (`/admin/users` in the dashboard, or the
  `/api/users` endpoints); and role management: create, edit, and delete roles
  (`/admin/roles` in the dashboard, or the `/api/roles` endpoints).

Role administration is gated by its own granular permissions rather than one
combined "manage roles" permission:

- `roles.view` - view roles and their permission assignments.
- `roles.create` - create new roles.
- `roles.update` - rename a role, edit its description, or change its
  permission assignments.
- `roles.delete` - delete a role (blocked for the system `admin` role, and for
  any role still assigned to a user).

Similarly, user administration has a dedicated `users.delete` permission
alongside `users.view`/`users.create`/`users.update`. Deleting a user removes
their account and any active sessions; a user can never delete their own
account, from either the dashboard or the API.
