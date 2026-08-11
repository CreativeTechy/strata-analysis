# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

Pipeline: Scrapy spider → AI enrichment → Supabase/Postgres → FastAPI → React dashboard.

- `backend/scraper/spiders/source_rss.py` - Scrapy spider; reads sources from the `sources` table (scoped to the selected project's sources when `PIPELINE_PROJECT_ID` is set), discovers article links, extracts text via trafilatura.
- `backend/services/articles/enrich.py` - tags/cleans articles using the configured LLM (via `llm_client.chat_completion`), falling back to neutral defaults if the call fails.
- `backend/services/articles/store.py` - upserts enriched articles into Supabase.
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
Run pipeline manually: `scrapy crawl source_rss -O articles.json` then `python -m services.articles.enrich`.

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
