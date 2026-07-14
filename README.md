# Strata Media - Source Intelligence

Strata Media ingests content from configured sources, enriches it with AI, stores
it in Supabase, and surfaces it in the dashboard.

## Pipeline

- `backend/scraper/` - Scrapy project for source and page extraction
- `backend/enrich.py` - AI enrichment stage
- `backend/store.py` - Supabase upsert layer
- `backend/main.py` - FastAPI API for scraping, sources, projects, and chat
- `dashboard/` - React + Vite dashboard

## Stages

1. Scraper - `backend/scraper/spiders/source_rss.py`. Reads sources from
   Supabase `sources` or the `SOURCES` env var override, discovers article links,
   and extracts clean title/date/text with trafilatura.
2. Enricher - `backend/enrich.py`. Cleans and tags each article with DeepSeek,
   then falls back to neutral defaults if the request fails.
3. Saver - `backend/store.py`. Upserts enriched articles into Supabase.
4. Dashboard - `dashboard/`. Reads live data from Supabase and calls the
   backend API.

DeepSeek is used everywhere in this app for AI: article enrichment
(`backend/enrich.py`), Intelligence Copilot chat (`backend/main.py`), and
hashtag/keyword/username/source discovery (`backend/projects_ai.py` and
`backend/project_discovery.py`).

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
- `DEEPSEEK_API_KEY` - required for enrichment, Intelligence Copilot chat, and
  project/source discovery

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

### 4. Run the dashboard locally

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

### 5. Run the pipeline manually

You can run the scrape/enrich/save flow directly from the backend folder:

```bash
scrapy crawl source_rss -O articles.json
python enrich.py
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
- `DEEPSEEK_API_KEY=...` - required for enrichment, Intelligence Copilot chat,
  and project/source discovery

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

### Reset the database (fresh start)

`schema.sql` only runs automatically against an empty Postgres volume, so if
your local schema ever drifts from `schema.sql` (e.g. leftover tables from a
rename), drop the volume and rebuild:

```bash
docker compose down -v
docker compose up --build -d
```

This deletes all local data and recreates the database from the current
`schema.sql` on next startup.

## Deployment Notes

For a production-style deployment, the important pieces are:

- PostgreSQL must be reachable by the backend container
- `backend/.env` must include the database URL and `DEEPSEEK_API_KEY`

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
- **admin** - everything above, plus user management: create users, change
  roles, and enable/disable accounts (`/admin/users` in the dashboard, or the
  `/api/users` endpoints).
