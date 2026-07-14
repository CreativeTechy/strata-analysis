# Strata Media - Source Intelligence

Strata Media ingests content from configured sources, enriches it with AI, stores
it in Supabase, and surfaces it in the dashboard.

## Pipeline

- `backend/scraper/` - Scrapy project for source and page extraction
- `backend/enrich.py` - AI enrichment stage
- `backend/store.py` - Supabase upsert layer
- `backend/main.py` - FastAPI API for scraping, sources, events, and chat
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
hashtag/keyword/username/source discovery (`backend/events_ai.py` and
`backend/event_discovery.py`).

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
  event/source discovery

### 3. Run the backend locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-optional.txt
uvicorn main:app --port 8000
```

If you only want the core API and not Spider Mode, you can skip the optional
requirements file.

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
  and event/source discovery

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

## Deployment Notes

For a production-style deployment, the important pieces are:

- PostgreSQL must be reachable by the backend container
- `backend/.env` must include the database URL and `DEEPSEEK_API_KEY`

The current Docker setup is suitable for a single-server deployment where the
database, backend, frontend, and reverse proxy all run together.

If you deploy the backend separately from the dashboard, keep the API base URL
consistent with the frontend's `VITE_API_TARGET` setting.

## Spider Mode

Spider Mode is the separate deep-crawl view powered by `backend/spider.py` and
`GET /api/spider/stream`.
