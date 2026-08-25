# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture

Pipeline: uploaded document → text extraction → LLM splits it into articles → human review → AI analysis stage pipeline → Postgres → FastAPI → React dashboard.

This is a fork of Strata Media with the entire online tier removed. There is no scraper, no `sources` table, no crawl scheduling, and no `/scrape` endpoint: everything the app analyzes is uploaded by the operator or imported from a JSONL export. `LLM_PROVIDER` defaults to `ollama` for the same reason - the documents being analyzed are exactly the kind of material that should not leave the machine. When touching anything here, the load-bearing assumption is **nothing fetches from the network except the configured LLM (and, opt-in, Hugging Face inference)**.

- `backend/services/documents/extraction.py` - shared text extraction for both document domains: text layer where the file has one, OCR (pytesseract) where it doesn't.
- `backend/services/documents/records.py` - the other kind of uploaded file: `.json`/`.jsonl`/`.ndjson` are *already* a list of articles (a JSONL export from `/api/articles/export`, or any article-shaped list), so they take a no-OCR, no-LLM branch of `project_documents_store.process_document` - one candidate per record, capped at `MAX_RECORDS` per file. Only `url`/`author`/`published` ride along (`record_metadata` on the candidate); `published` matters because every trend read keys off the `published_at` `save_articles()` parses out of it. Accepted on the opinion-monitor upload step rather than as a second import endpoint - the review-then-approve step is the point of that wizard.
- `backend/services/projects/project_documents_store.py` / `project_document_articles.py` - opinion-monitor documents: upload → extract → LLM-split into candidate articles → approve → materialize into `articles` and queue analysis. An approved candidate's article gets `source` = the document's filename and `source_url` = `document://project-document/<document_id>`, so every article split out of the same file groups under it (that is what the Articles page's document filter and the keyword-existence document filter read); `url` stays per-article because it is the unique key.
- `backend/services/competitors/competitor_documents_store.py` / `competitor_document_articles.py` - the same flow for competitor studies, writing to the competitor-side tables.
- `backend/services/competitors/document_analysis.py` - names the companies a study's approved articles are actually about, tracks each as a competitor, then hands off to `competitor_analysis.generate_findings`. This is how a study gets its competitor set: there is no discovery and no channels to validate.
- `backend/analysis/` - the AI stage pipeline (language → sentiment → classification → structured extraction → entities → aggregation). `orchestrator.analyze_article()` is the entry point.
- `backend/services/articles/analysis_defaults.py` - `DEFAULT_ENRICHMENT` (the complete neutral analysis dict every "not analyzed yet" article starts from) and `FATAL_ANALYSIS_ERRORS` (the provider failures that mean "stop, everything else fails identically" rather than "this article failed"). With a local model the most common failure is exactly `LLMConnectionError` - the model server isn't running - so this distinction is what keeps a run from reporting 400 individually-failed articles instead of one unreachable host.
- `backend/services/articles/reanalyze.py` - `reanalyze_article(article_id, run_id=...)`: re-runs the stage pipeline for one article and saves it. Used both for one-off retries (via FastAPI BackgroundTasks) and in bulk by the analysis pipeline.
- `backend/services/pipeline/pipeline.py` - `run_analysis_pipeline(run_id, project_id, scope)`: one *analysis run*. Selects the project's in-scope articles (`scope="pending"` = analysis hasn't succeeded yet, `scope="all"` = everything), analyzes them through a small thread pool (`ANALYSIS_CONCURRENCY`, default 2), and writes progress to `pipeline_runs`/`pipeline_run_documents` per article so the dashboard fills in live. It is a worker thread, not a subprocess - cancellation is a flag checked at each article boundary, so a stop lands within one article.
- `backend/services/pipeline/pipeline_runs.py` - run tracking. Counters are `articles_selected`/`articles_analyzed`/`articles_failed`; stages are `prepare` and `analyze`; the per-run breakdown is per *document* (`pipeline_run_documents`), a document being this product's unit of provenance the way a source was in the crawler.
- `backend/services/articles/store.py` - upserts analyzed articles into Postgres. An article belongs to the project the caller names; there is no source-based inference of linkage any more.
- `backend/main.py` - FastAPI app: auth, users/roles, projects, articles, analysis runs (`POST /api/analysis-runs`), Intelligence Copilot chat.
- `backend/services/` - business logic by domain: `auth/` (login, sessions, users, RBAC), `projects/`, `competitors/` (competitor study), `articles/` (analysis defaults, storage, reanalysis, JSONL import), `pipeline/` (analysis run execution + tracking), `intelligence/` (analytics). `backend/analysis/` and `migrate.py` stay at `backend/` root.
- `backend/config.py` - single source of truth for credentials and tuning; loads `backend/.env` manually (not python-dotenv). Resolves the active LLM provider (`LLM_PROVIDER`) and its credentials/base URL/model.
- `backend/llm_client.py` - provider-neutral `chat_completion(...)`; the only module aware of Ollama/DeepSeek (chat-completions) vs. OpenAI (Responses) request-shape differences.
- `dashboard/` - React 19 + Vite dashboard. "Analysis Runs" is the run history and the place a run is started; "Performance Logs" is per-article analysis health.

Tests live in `backend/tests/` and run with `python -m pytest tests -q` from `backend/`.

## Commands

Backend (from `backend/`):
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --port 8000
python -m pytest tests -q
```

Dashboard (from `dashboard/`):
```
npm install
npm run dev       # dev server, expects backend at http://localhost:8000 (override via VITE_API_TARGET)
npm run build
npm run lint      # eslint .
```

Docker (full stack from repo root): `docker compose up --build`
- Public app on `:8210` (nginx), backend proxied at `/api`, Adminer on `:8082`, Postgres in `db`, local LLM in `ollama` (+ one-shot `ollama-pull`).
- Backend container reads `backend/.env`. Point `OLLAMA_CHAT_BASE_URL` at `http://ollama:11434/v1/chat/completions` there - a localhost URL resolves to the backend container itself.

## Constraints

- Required backend env vars: the database credentials - `POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD` in `backend/.env`, which `db.get_database_url()` assembles into a connection string, or an explicit `DATABASE_URL` that overrides them. docker-compose's `db` service reads the same file, so the Postgres credentials are defined once. No API key is needed for the default `LLM_PROVIDER=ollama`; `OPENAI_API_KEY`/`DEEPSEEK_API_KEY` only matter if you switch to those.
- `LLM_PROVIDER` (`ollama` default, or `openai`, or `deepseek`) picks the app-wide provider. All provider selection, credentials, and request-shape differences are centralized in `backend/config.py` and `backend/llm_client.py`; feature modules only call `llm_client.chat_completion(...)` and never branch on the provider. Switching to a hosted provider sends uploaded document text to that provider - treat that as a product decision, not a config tweak.
- `COMPETITOR_ANALYSIS_LLM_PROVIDER` optionally overrides the provider for just `backend/services/competitors/`'s document splitting, competitor naming, and finding generation - e.g. a larger local model for finding generation while the rest of the app uses a faster one. Left unset, it inherits `LLM_PROVIDER`. `chat_completion(...)` takes matching `api_key`/`base_url`/`api_style`/`reasoning_effort`/`model` overrides; `config.COMPETITOR_LLM_*` resolves them the same way `config.LLM_*` resolves the app-wide ones.
- OpenAI is called via its Responses API (`OPENAI_CHAT_MODEL`/`OPENAI_CHAT_BASE_URL` overridable; default `gpt-5-nano`); DeepSeek and Ollama via the OpenAI-compatible chat-completions shape (`DEEPSEEK_CHAT_MODEL`/`OLLAMA_CHAT_MODEL` etc.).
- `EMBEDDING_MODEL`/`EMBEDDING_DEVICE` run locally via sentence-transformers; unrelated to the chat LLM, and they compete with a local Ollama for the same CPU/GPU.
- `SENTIMENT_CLASSIFIER_PROVIDER` and `CLASSIFICATION_PROVIDER` (`local` default, or `hf_api`) independently pick whether that stage's model runs in-process (`transformers.pipeline`) or via Hugging Face's hosted Inference API (`backend/hf_inference_client.py`). `hf_api` needs `HF_API_TOKEN` and only `huggingface_hub` (no torch), but it does send text off the machine; `local` needs `transformers`/torch installed.
- `ANALYSIS_CONCURRENCY` (`2` by default) - how many articles one analysis run analyzes in parallel. Deliberately low: with a local model the ceiling is one model server, which is also competing with the embedding model. Raise it only after watching what the host actually sustains.
- `STALE_RUN_MINUTES` (`180`) - how long a queued/running analysis run blocks a new run for the same project before it is treated as abandoned. Without it, a backend that died mid-run would block that project forever.
- `LLM_REQUEST_TIMEOUT_SECONDS` (`60`) - a slow local model, especially CPU-only, can legitimately exceed this; raise it before lowering concurrency.
- Keep `VITE_API_TARGET` (dashboard) consistent with the backend's actual base URL if deployed separately.
- Uploaded files live under `storage/` (bind-mounted into the backend container), so that path has to persist alongside the database. LLM system prompts live in `storage/prompts/` and are loaded by `backend/prompt_loader.py`.
