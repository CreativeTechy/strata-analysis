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
2. Enricher - `backend/enrich.py`. Cleans and tags each article with DeepSeek,
   then falls back to neutral defaults when `DEEPSEEK_API_KEY` is unset.
3. Saver - `backend/store.py`. Upserts enriched articles into Supabase.
4. Dashboard - `dashboard/`. Reads live data from Supabase and calls the
   backend API.

## Setup

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --port 8000
```

Run the pipeline directly without the API:

```bash
scrapy crawl source_rss -O articles.json
python enrich.py
```

### Dashboard

```bash
cd dashboard
npm install
npm run dev
```

## Spider Mode

Spider Mode is the separate deep-crawl view powered by `backend/spider.py` and
`GET /api/spider/stream`.

