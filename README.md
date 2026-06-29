# Strata Media — Car News Intelligence

A pipeline that scrapes automotive news, enriches it with AI, stores it in
Supabase, and surfaces it in a dashboard.

```
  Supabase `feeds`
     │
     ▼
┌──────────┐   ┌───────────┐   ┌─────────┐   ┌──────────────┐
│ SCRAPER  │──▶│ ENRICHER  │──▶│  SAVER  │──▶│  Supabase    │──▶ DASHBOARD
│ Scrapy + │   │ DeepSeek  │   │ upsert  │   │  articles    │    (React/Vite)
│trafilatura│   │           │   │         │   │  table       │
└──────────┘   └───────────┘   └─────────┘   └──────────────┘
 carnews_rss      enrich.py      store.py
```

## Layout

```
backend/                 Python pipeline + FastAPI
  config.py              load_feeds() + env-based credentials
  carnews/               Scrapy project (the scraper)
    spiders/carnews_rss.py
  enrich.py              DeepSeek enrichment (the enricher)
  store.py               single Supabase upsert (the saver)
  main.py                FastAPI: /scrape, /api/health, /api/feeds
  schema.sql             Supabase table + RLS policy
  render.yaml            Render deploy for the API
dashboard/               React + Vite UI (reads live from Supabase)
.github/workflows/       scheduled scrape (every 12h) + manual dispatch
```

## Stages

1. **Scraper** — `carnews/spiders/carnews_rss.py`. Reads sources from
   Supabase `feeds` (or the `FEEDS` env var override) via `config.load_feeds()`,
   follows each RSS/Atom entry, and extracts clean title/date/text with
   trafilatura. Add or remove a publisher from the dashboard — no code change.
2. **Enricher** — `enrich.py`. Cleans/dedupes, then tags each article with
   DeepSeek (summary, brands, car_models, sentiment, category, relevance). Falls
   back to neutral defaults if `DEEPSEEK_API_KEY` is unset.
3. **Saver** — `store.py`. One upsert path into Supabase `articles`
   (on_conflict=url, merge-duplicates).
4. **Dashboard** — `dashboard/`. Reads live from Supabase with the public anon
   key; the "Run Extractor" button POSTs `/scrape` to the backend.

## Setup

### Database
Run `backend/schema.sql` in the Supabase SQL editor (creates `articles` + the
anon-read RLS policy).

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in SUPABASE_URL, SUPABASE_SERVICE_KEY, DEEPSEEK_API_KEY
uvicorn main:app --port 8000
```
Run the pipeline directly without the API:
```bash
scrapy crawl carnews_rss -O articles.json
python enrich.py
```

### Dashboard
```bash
cd dashboard
npm install
npm run dev   # proxies /scrape and /api to the backend (VITE_API_TARGET)
```

## Automation
`.github/workflows/scraper.yml` runs the scrape+enrich+save every 12h (and on
manual dispatch). Required repo secrets: `DEEPSEEK_API_KEY`, `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`.

## Spider Mode (deep crawl at scale)

A separate dashboard page (`Spider Mode`) that deep-crawls a seed URL with BFS
fan-out and streams a live crawl graph + big-number counters (pages, articles,
words harvested) — the volume layer that feeds the downstream analytics work.

- Backend: `backend/spider.py` + SSE endpoint `GET /api/spider/stream`.
- Two engines, same output: a **native** engine (requests + parsel + trafilatura,
  always available) and **Crawl4AI** (auto-used when installed — see
  `requirements-spider.txt`; needs Python ≤3.12). The page shows which ran.
- Run locally: start the backend (`uvicorn main:app --port 8000`) + dashboard
  (`npm run dev`), open Spider Mode, set a seed + depth + max pages, Launch.

## Security
Writes require the Supabase **service_role** key (env only — never committed).
The frontend anon key is public by design. If a service_role key was ever
committed, rotate it in the Supabase dashboard.
