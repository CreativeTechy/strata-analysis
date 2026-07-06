# Strata Media - Source Intelligence

Strata Media ingests content from configured feeds, enriches it with AI, stores
it in Supabase, and surfaces it in the dashboard.

## Pipeline

- `backend/scraper/` - Scrapy project for feed and page extraction
- `backend/enrich.py` - AI enrichment stage
- `backend/store.py` - Supabase upsert layer
- `backend/main.py` - FastAPI API for scraping, feeds, events, and chat
- `dashboard/` - React + Vite dashboard

## Stages

1. Scraper - `backend/scraper/spiders/source_rss.py`. Reads sources from
   Supabase `feeds` or the `FEEDS` env var override, discovers article links,
   and extracts clean title/date/text with trafilatura.
2. Enricher - `backend/enrich.py`. Cleans and tags each article with the local
   LLM, then falls back to neutral defaults when the local model is
   unavailable.
3. Saver - `backend/store.py`. Upserts enriched articles into Supabase.
4. Dashboard - `dashboard/`. Reads live data from Supabase and calls the
   backend API.

DeepSeek is still used in `backend/events_ai.py` and `backend/event_discovery.py`
for hashtag, keyword, username, and feed discovery.

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
- `DEEPSEEK_API_KEY` if you want event/source discovery
- `LOCAL_LLM_BASE_URL`
- `LOCAL_LLM_MODEL`

For local article enrichment and Intelligence Copilot, this project defaults to:

- `LOCAL_LLM_BASE_URL=http://localhost:11434/v1`
- `LOCAL_LLM_MODEL=qwen2.5:14b-instruct`

### 3. Download a local model

The recommended local setup is Ollama:

```bash
ollama pull qwen2.5:14b-instruct
```

If your hardware is limited, use a smaller model:

```bash
ollama pull qwen2.5:7b-instruct
```

### 4. Run the backend locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-optional.txt
uvicorn main:app --port 8000
```

If you only want the core API and not Spider Mode, you can skip the optional
requirements file.

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
- `LOCAL_LLM_BASE_URL=http://host.docker.internal:11434/v1` if Ollama runs on the host
- `LOCAL_LLM_MODEL=qwen2.5:14b-instruct`
- `DEEPSEEK_API_KEY=...` if you want event/source discovery enabled

If you run Ollama in a separate container instead of on the host, point
`LOCAL_LLM_BASE_URL` to that container's service name and port.

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
- `backend/.env` must include the database URL and LLM settings
- the local LLM endpoint must be reachable from the backend
- `DEEPSEEK_API_KEY` is only needed if you want feed/source discovery enabled

The current Docker setup is suitable for a single-server deployment where the
database, backend, frontend, and reverse proxy all run together.

If you deploy the backend separately from the dashboard, keep the API base URL
consistent with the frontend's `VITE_API_TARGET` setting.

## Spider Mode

Spider Mode is the separate deep-crawl view powered by `backend/spider.py` and
`GET /api/spider/stream`.
