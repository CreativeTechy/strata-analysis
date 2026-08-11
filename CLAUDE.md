# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

Pipeline: Scrapy spider → AI enrichment → Supabase/Postgres → FastAPI → React dashboard.

- `backend/scraper/spiders/source_rss.py` - Scrapy spider; reads sources from the `sources` table (scoped to the selected project's sources when `PIPELINE_PROJECT_ID` is set), discovers article links, extracts text via trafilatura. `keyword` sources are crawled three ways: their Google News RSS feed (`googlenewsdecoder` resolves each item's `news.google.com/rss/articles/...` redirect-wrapper link to the real publisher URL before fetching it), GDELT's free news-search API (`backend/scraper/gdelt.py`, on by default - toggle with `GDELT_ENABLED`) fetched directly as articles, and - when `GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_ENGINE_ID` are set - a general web search via `backend/scraper/web_search.py`, crawled like a `web` source.
- `backend/services/articles/enrich.py` - clean/dedup/date-window-filter/analyze logic for one article at a time (tags/cleans using the configured LLM via `llm_client.chat_completion`, falling back to neutral defaults if the call fails). Its own `main()` is a batch CLI entry point (reads a raw-scrape JSON file, loops over every article, writes an enriched JSON file) for the manual/offline workflow below; `backend/scraper/pipelines.py`'s `StreamingEnrichPipeline` reuses these same functions per-article from inside the live crawl instead - see below.
- `backend/scraper/pipelines.py` - Scrapy item pipeline that cleans/enriches/embeds/saves each article the moment it's scraped (calling into `enrich.py`'s functions), rather than waiting for the whole crawl to finish before enriching anything. Self-disables (`NotConfigured`) unless `PIPELINE_RUN_ID` is set, so a bare manual `scrapy crawl` is unaffected. This is why the dashboard's per-source breakdown for a run fills in source by source instead of only appearing once the slowest source finishes. Enriches up to `ENRICH_CONCURRENCY` articles in parallel via a dedicated Twisted thread pool (`deferToThreadPool`), guarding its shared in-memory counters with a lock; the LLM/embedding calls themselves run outside that lock.
- `backend/services/articles/store.py` - upserts enriched articles into Supabase.
- `backend/services/pipeline/pipeline.py` - `run_scraper_pipeline()`: runs the single `scrapy crawl source_rss` subprocess described above end to end (scrape+clean+enrich+save all interleaved), then folds the spider's end-of-run fetch diagnostics (blocked/404/DNS-failed - only knowable once the whole crawl closes) into the per-source rows the streaming pipeline already wrote live.
- `backend/main.py` - FastAPI app: scraping, sources, projects, chat (Intelligence Copilot, also via `llm_client.chat_completion`) endpoints.
- `backend/services/projects/projects_ai.py` / `backend/services/projects/project_discovery.py` - call the configured LLM via `llm_client.chat_completion` for hashtag/keyword/username/source discovery.
- `backend/config.py` - single source of truth for source list and credentials; loads `backend/.env` manually (not python-dotenv). Also resolves the active LLM provider (`LLM_PROVIDER`) and its credentials/base URL/model.
- `backend/llm_client.py` - provider-neutral `chat_completion(...)` client; the only module aware of OpenAI vs. DeepSeek request/response differences.
- `backend/hf_inference_client.py` - thin wrapper around `huggingface_hub.InferenceClient` (the official client, not hand-rolled HTTP - HF has already retired one hosted-inference URL in favor of provider-routed `router.huggingface.co`); used by `sentiment_classifier.py`/`backend/analysis/classification.py` when their provider is set to `hf_api` instead of `local`.
- `backend/services/` - business-logic modules grouped by domain: `auth/` (login, sessions, users, RBAC), `projects/`, `sources/`, `competitors/` (competitor study), `articles/` (enrichment/storage/reanalysis), `pipeline/` (scrape→enrich→save execution, run tracking, scheduling), `intelligence/` (analytics). `backend/analysis/` (the AI stage pipeline) and standalone ops scripts (`migrate.py`, `seed_competitor_demo.py`) stay at `backend/` root.
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
Run pipeline manually (offline/dev, no `PIPELINE_RUN_ID` - the streaming item pipeline stays disabled): `scrapy crawl source_rss -O articles.json` then `python -m services.articles.enrich`. The backend-triggered pipeline (`/scrape` endpoint, scheduler) instead runs a single `scrapy crawl source_rss` with `PIPELINE_RUN_ID` set, streaming clean+enrich+save per article - see `backend/scraper/pipelines.py`.

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

- Required backend env vars: `DATABASE_URL`, plus the active LLM provider's key (`DEEPSEEK_API_KEY` by default; `OPENAI_API_KEY` if `LLM_PROVIDER=openai`; not needed for `LLM_PROVIDER=ollama`) - used for all AI: enrichment, Copilot chat, project/source discovery.
- `LLM_PROVIDER` (`deepseek` default, or `openai`, or `ollama` for a fully local/offline setup) picks the app-wide provider; all provider selection, credentials, and request-shape differences are centralized in `backend/config.py` and `backend/llm_client.py`. Feature modules only call `llm_client.chat_completion(...)` and never branch on the provider. `ollama` talks to a local `ollama serve` (default `http://localhost:11434/v1/chat/completions`), which speaks the same OpenAI-compatible chat-completions shape as DeepSeek.
- `COMPETITOR_ANALYSIS_LLM_PROVIDER` optionally overrides the provider for just `backend/services/competitors/`'s document splitting (`competitor_document_articles.py`), competitor naming (`document_analysis.py`), and finding generation (`competitor_analysis.py`) - e.g. `ollama` there while the rest of the app (enrichment, Copilot, discovery) keeps using `LLM_PROVIDER`. Left unset, it inherits `LLM_PROVIDER`. `chat_completion(...)` takes matching `api_key`/`base_url`/`api_style`/`reasoning_effort`/`model` overrides for this; `config.COMPETITOR_LLM_*` resolves them the same way `config.LLM_*` resolves the app-wide ones. Competitor discovery (`competitor_discovery.py`) and the business-profile scraper (`business_profile_store.py`) are deliberately excluded - both need live web access regardless of provider.
- OpenAI is called via its Responses API (`OPENAI_CHAT_MODEL`/`OPENAI_CHAT_BASE_URL` overridable; default model `gpt-5-nano`); DeepSeek via its OpenAI-compatible chat-completions API (`DEEPSEEK_CHAT_MODEL`/`DEEPSEEK_CHAT_BASE_URL` overridable; default model `deepseek-chat`).
- `EMBEDDING_MODEL`/`EMBEDDING_DEVICE` still run locally via sentence-transformers; unrelated to the chat LLM.
- `SENTIMENT_CLASSIFIER_PROVIDER` and `CLASSIFICATION_PROVIDER` (`local` default, or `hf_api`) independently pick whether that stage's model runs in-process (`transformers.pipeline`) or via Hugging Face's hosted Inference API (`backend/hf_inference_client.py`, `huggingface_hub.InferenceClient`). `hf_api` mode needs `HF_API_TOKEN` (or `HF_TOKEN`) set and only the lightweight `huggingface_hub` package (no torch); `local` mode needs `transformers`/torch installed and ignores `HF_API_*`. Leave `HF_API_BASE_URL` unset unless pointing at a dedicated HF Inference Endpoint - InferenceClient resolves HF's shared routing host itself.
- Keep `VITE_API_TARGET` (dashboard) consistent with the backend's actual base URL if deployed separately.
- `GOOGLE_CSE_API_KEY`/`GOOGLE_CSE_ENGINE_ID` (both optional, unset by default) enable the general-web-search tier for `keyword` sources - see `backend/scraper/web_search.py`. Unset, keyword sources are scraped via Google News RSS + GDELT only.
- `GDELT_ENABLED` (`true` by default, no credentials needed) - GDELT's free DOC 2.0 news-search API tier for `keyword` sources, see `backend/scraper/gdelt.py`. GDELT itself rate-limits to roughly one request per 5 seconds (undocumented exactly, observed stricter in practice); `gdelt.py` throttles its own calls to stay under that, so a project with many keywords takes correspondingly longer to seed this tier. Set `false` to disable.
- `ENRICH_CONCURRENCY` (`4` by default) - how many articles `StreamingEnrichPipeline` enriches in parallel. Deliberately conservative rather than tuned to one provider: DeepSeek has no published RPM limit but a shared 500-2500 in-flight-request cap at the account level (across everything else that account does too); OpenAI's Tier 1 (by cumulative spend) is comfortably above this default for a small/cheap model but not unlimited; Ollama has no external limit but real local hardware/VRAM throughput instead, and also competes with the local embedding model for the same CPU/GPU. Raise it only after confirming your own provider/host handles it.
