# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

Pipeline: Scrapy spider → AI enrichment → Supabase/Postgres → FastAPI → React dashboard.

- `backend/scraper/spiders/source_rss.py` - Scrapy spider; reads sources from the `sources` table (or `SOURCES` env var override), discovers article links, extracts text via trafilatura.
- `backend/enrich.py` - tags/cleans articles using DeepSeek (via `llm_client.chat_completion`), falling back to neutral defaults if the call fails.
- `backend/store.py` - upserts enriched articles into Supabase.
- `backend/main.py` - FastAPI app: scraping, sources, projects, chat (Intelligence Copilot, also DeepSeek) endpoints.
- `backend/projects_ai.py` / `backend/project_discovery.py` - call DeepSeek directly (not via `llm_client`) for hashtag/keyword/username/source discovery.
- `backend/config.py` - single source of truth for source list and credentials; loads `backend/.env` manually (not python-dotenv).
- `dashboard/` - React 19 + Vite dashboard, reads Supabase directly and calls the backend API.

No automated test suite exists in this repo.

## Commands

Backend (from `backend/`):
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-optional.txt   # needed for local embeddings (sentence-transformers)
uvicorn main:app --port 8000
```
Run pipeline manually: `scrapy crawl source_rss -O articles.json` then `python enrich.py`.

Dashboard (from `dashboard/`):
```
npm install
npm run dev       # dev server, expects backend at http://localhost:8000 (override via VITE_API_TARGET)
npm run build
npm run lint      # eslint .
```

Docker (full stack from repo root): `docker compose up --build`
- Public app on `:80` (nginx), backend proxied at `/api` and `/scrape`, Adminer on `:8080`, Postgres in `db` service.
- Backend container reads `backend/.env`.

## Constraints

- Required backend env vars: `DATABASE_URL`, `DEEPSEEK_API_KEY` (used for all AI: enrichment, Copilot chat, project/source discovery).
- All LLM calls go through DeepSeek's API (`deepseek-chat` by default, `DEEPSEEK_CHAT_MODEL`/`DEEPSEEK_CHAT_BASE_URL` overridable) — there is no local/self-hosted LLM anymore.
- `EMBEDDING_MODEL`/`EMBEDDING_DEVICE` still run locally via sentence-transformers; unrelated to the chat LLM.
- Keep `VITE_API_TARGET` (dashboard) consistent with the backend's actual base URL if deployed separately.
