"""FastAPI service that orchestrates the pipeline.

The four stages live in their own modules:
  scraper  -> scraper/spiders/source_rss.py (Scrapy)
  enricher -> enrich.py
  saver    -> store.py

This API triggers the jobs and exposes configured sources to the dashboard.
"""

import asyncio
import contextlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from event_discovery import discover_event_links
from events_ai import suggest_event_metadata
from articles_store import export_articles, get_article_stats, list_articles
from articles_store import get_brand_sentiment_rollup
from llm_client import chat_completion
from events_store import (
    create_event,
    delete_event,
    diagnose_event_setup,
    list_events,
    list_events_page,
    list_sources_for_event,
    persist_event_embedding_for_id,
    record_run_completion,
    set_event_sources,
    update_event,
)
from sources_store import (
    bootstrap_sources,
    create_source,
    delete_source,
    diagnose_source_setup,
    list_sources_page,
    update_source,
)
from pipeline import cancel_pipeline_run, run_scraper_pipeline
from pipeline_runs import (
    ACTIVE_STATUSES,
    create_pipeline_run,
    get_active_run_for_event,
    get_pipeline_run,
    list_pipeline_runs,
    update_pipeline_run,
)
from scheduler import scheduler_loop

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR.parent / "storage"


def _load_text_asset(filename, fallback=""):
    path = STORAGE_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return fallback.strip()


COPILOT_SYSTEM_PROMPT = _load_text_asset("copilot_system_prompt.txt")

app = FastAPI(title="Strata Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _format_event_context(event: dict | None) -> str:
    if not isinstance(event, dict):
        return ""

    parts = []
    name = (event.get("name") or "").strip()
    if name:
        parts.append(f"Name: {name}")

    status = (event.get("status") or "").strip()
    if status:
        parts.append(f"Status: {status}")

    start_date = event.get("start_date")
    if start_date:
        parts.append(f"Start date: {start_date}")

    end_date = event.get("end_date")
    if end_date:
        parts.append(f"End date: {end_date}")

    location = (event.get("location") or "").strip()
    if location:
        parts.append(f"Location: {location}")

    target_audience = (event.get("target_audience") or "").strip()
    if target_audience:
        parts.append(f"Target audience: {target_audience}")

    hashtags = event.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = [hashtags]
    hashtags = [str(item).strip() for item in hashtags if str(item).strip()]
    if hashtags:
        parts.append(f"Hashtags: {', '.join(hashtags)}")

    keywords = event.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [str(item).strip() for item in keywords if str(item).strip()]
    if keywords:
        parts.append(f"Keywords: {', '.join(keywords)}")

    usernames = event.get("usernames") or []
    if isinstance(usernames, str):
        usernames = [usernames]
    usernames = [str(item).strip() for item in usernames if str(item).strip()]
    if usernames:
        parts.append(f"Usernames: {', '.join(usernames)}")

    description = (event.get("description") or "").strip()
    if description:
        parts.append(f"Description: {description}")

    return "\n".join(parts)


@app.on_event("startup")
async def _start_scheduler():
    app.state.scheduler_task = asyncio.create_task(scheduler_loop())


@app.on_event("shutdown")
async def _stop_scheduler():
    task = getattr(app.state, "scheduler_task", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@app.get("/")
def root():
    return {"service": "Strata Spider API", "ok": True, "see": "/api/health"}


@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "Strata Scraper API"}


@app.get("/api/sources")
def get_sources(limit: int | None = None, offset: int = 0):
    """Configured sources for the dashboard sidebar."""
    if limit is None:
        sources = bootstrap_sources()
        source = sources[0].get("source", "database") if sources else "database"
        return {"sources": sources, "source": source}

    page = list_sources_page(limit=limit, offset=offset)
    source = page["sources"][0].get("source", "database") if page["sources"] else "database"
    return {**page, "source": source}


@app.get("/api/events")
def get_events(limit: int | None = None, offset: int = 0):
    if limit is None:
        return {"events": list_events()}
    return list_events_page(limit=limit, offset=offset)


def _default_discovery_result(event):
    source_ids = []
    for value in event.get("source_ids") or []:
        try:
            source_ids.append(int(value))
        except Exception:
            continue
    return {
        "search_terms": [],
        "candidates": [],
        "suggested_links": [],
        "source_ids": source_ids,
        "sources": [],
    }


def _save_event_with_discovery(event):
    if not isinstance(event, dict):
        return None, {}

    discovery = (
        discover_event_links(event)
        if (event.get("hashtags") or event.get("keywords") or event.get("usernames"))
        else _default_discovery_result(event)
    )
    if discovery.get("source_ids") is not None:
        event = {**event, "source_ids": discovery.get("source_ids") or event.get("source_ids") or []}
    return event, discovery


@app.post("/api/events/discover")
def discover_event(payload: dict):
    if not isinstance(payload, dict):
        payload = {}
    discovery = discover_event_links(payload)
    return {"discovery": discovery}


@app.post("/api/events")
def add_event(background_tasks: BackgroundTasks, payload: dict):
    try:
        event = create_event(payload or {}, embed=False)
    except ValueError as e:
        return {"error": "Invalid event payload.", "detail": str(e)}
    except Exception as e:
        detail = diagnose_event_setup()
        return {
            "error": "Unable to create event. Check database connection settings.",
            "detail": detail or str(e),
        }
    if not event:
        detail = diagnose_event_setup()
        return {
            "error": "Unable to create event. Check database connection settings.",
            "detail": detail or "The event request did not return a row.",
        }
    background_tasks.add_task(persist_event_embedding_for_id, event.get("id"))
    return {"event": event}


@app.put("/api/events/{event_id}")
def edit_event(event_id: int, background_tasks: BackgroundTasks, payload: dict):
    try:
        event = update_event(event_id, payload or {}, embed=False)
    except ValueError as e:
        return {"error": "Invalid event payload.", "detail": str(e)}
    except Exception as e:
        detail = diagnose_event_setup()
        return {
            "error": "Unable to update event. Check database connection settings.",
            "detail": detail or str(e),
        }
    if not event:
        detail = diagnose_event_setup()
        return {
            "error": "Unable to update event. Check database connection settings.",
            "detail": detail or "The update request did not return a row.",
        }
    background_tasks.add_task(persist_event_embedding_for_id, event_id)
    event, discovery = _save_event_with_discovery(event)
    return {"event": event, "discovery": discovery}


@app.post("/api/events/suggest")
def suggest_event(payload: dict):
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    if not name:
        return {
            "error": "Event name is required.",
            "detail": "Provide the event name before requesting AI suggestions.",
        }
    return {"suggestions": suggest_event_metadata(name, description)}


@app.delete("/api/events/{event_id}")
def remove_event(event_id: int):
    if not delete_event(event_id):
        detail = diagnose_event_setup()
        return {
            "error": "Unable to delete event. Check database connection settings.",
            "detail": detail or "The delete request failed.",
        }
    return {"ok": True}


@app.get("/api/pipeline-runs")
def get_pipeline_runs(limit: int = 10):
    return {"runs": list_pipeline_runs(limit=max(1, min(int(limit), 25)))}


@app.post("/api/pipeline-runs/{run_id}/stop")
def stop_pipeline_run(run_id: str):
    run = get_pipeline_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found.")

    if run["status"] not in ACTIVE_STATUSES:
        return {"run": run, "message": f"Run is already {run['status']}; nothing to stop."}

    cancel_pipeline_run(run_id)

    now = datetime.now(timezone.utc).isoformat()
    updated = update_pipeline_run(
        run_id,
        status="cancelled",
        stage="cancelled",
        message="Cancelled by user.",
        cancel_requested_at=now,
        cancelled_at=now,
        finished_at=now,
    )
    if run.get("event_id") is not None:
        record_run_completion(run["event_id"], status="cancelled", completed_at=datetime.now(timezone.utc))

    return {"run": updated or run, "message": "Pipeline run cancelled."}


@app.get("/api/articles")
def get_articles(
    search: str | None = None,
    sentiment: str | None = None,
    category: str | None = None,
    event_id: int | None = None,
    limit: int = 24,
    offset: int = 0,
    sort: str = "published.desc",
):
    return list_articles(
        search=search,
        sentiment=sentiment,
        category=category,
        event_id=event_id,
        limit=limit,
        offset=offset,
        sort=sort,
    )


@app.get("/api/articles/stats")
def get_articles_stats(
    search: str | None = None,
    category: str | None = None,
    event_id: int | None = None,
):
    return get_article_stats(search=search, category=category, event_id=event_id)


@app.get("/api/articles/export")
def export_articles_jsonl(
    search: str | None = None,
    sentiment: str | None = None,
    category: str | None = None,
    event_id: int | None = None,
    sort: str = "published.desc",
):
    rows = export_articles(
        search=search,
        sentiment=sentiment,
        category=category,
        event_id=event_id,
        sort=sort,
    )

    def line_stream():
        for row in rows:
            yield json.dumps(row, ensure_ascii=False, default=str) + "\n"

    filename = "articles-export.jsonl"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "application/x-ndjson; charset=utf-8",
    }
    return StreamingResponse(line_stream(), headers=headers, media_type="application/x-ndjson")


@app.post("/api/sources")
def add_source(payload: dict):
    """Create or update a source record in local PostgreSQL."""
    source = create_source(payload or {})
    if not source:
        detail = diagnose_source_setup()
        return {
            "error": "Unable to create source. Check database connection settings.",
            "detail": detail or "The source request did not return a row.",
        }
    return {"source": source}


@app.put("/api/sources/{source_id}")
def edit_source(source_id: int, payload: dict):
    """Update a source record in local PostgreSQL."""
    source = update_source(source_id, payload or {})
    if not source:
        detail = diagnose_source_setup()
        return {
            "error": "Unable to update source. Check database connection settings.",
            "detail": detail or "The update request did not return a row.",
        }
    return {"source": source}


@app.delete("/api/sources/{source_id}")
def remove_source(source_id: int):
    """Delete a source record from local PostgreSQL."""
    if not delete_source(source_id):
        detail = diagnose_source_setup()
        return {
            "error": "Unable to delete source. Check database connection settings.",
            "detail": detail or "The delete request failed.",
        }
    return {"ok": True}


@app.post("/api/events/{event_id}/sources")
def replace_event_sources(event_id: int, payload: dict):
    source_ids = payload.get("source_ids") if isinstance(payload, dict) else []
    assigned = set_event_sources(event_id, source_ids or [])
    return {"event_id": event_id, "source_ids": assigned}


@app.post("/scrape")
def trigger_scrape(background_tasks: BackgroundTasks, payload: dict | None = None):
    payload = payload or {}
    event_id = payload.get("event_id")
    try:
        event_id = int(event_id) if event_id is not None else None
    except Exception:
        event_id = None
    if event_id is None:
        events = list_events()
        if len(events) == 1:
            event_id = events[0].get("id")
        elif not events:
            raise HTTPException(status_code=400, detail="Create an event before running the scraper.")
        else:
            raise HTTPException(status_code=400, detail="Select an event before running the scraper.")

    if not list_sources_for_event(event_id):
        raise HTTPException(status_code=400, detail="Assign at least one source to the selected event before scraping.")

    active_run = get_active_run_for_event(event_id)
    if active_run:
        return {
            "message": "A pipeline run is already active for this event.",
            "run_id": active_run["id"],
            "event_id": event_id,
        }

    run = create_pipeline_run(status="queued", stage="queued", message="Queued for execution.", event_id=event_id)
    run_id = run["id"] if run else uuid.uuid4().hex
    background_tasks.add_task(run_scraper_pipeline, run_id, event_id)
    return {
        "message": "Scraper pipeline triggered. It will save to local PostgreSQL when finished.",
        "run_id": run_id,
        "event_id": event_id,
    }


@app.get("/api/spider/stream")
async def spider_stream(seed: str, depth: int = 2, pages: int = 300, save: int = 0):
    """Server-Sent Events: live deep crawl for the Spider Mode page."""
    depth = max(1, min(int(depth), 4))
    pages = max(10, min(int(pages), 2000))

    async def gen():
        try:
            from spider import deep_crawl_stream
            from store import save_crawl_pages
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Spider engine unavailable: {e}'})}\n\n"
            return

        crawl_id = uuid.uuid4().hex
        fetched_at = datetime.now(timezone.utc).isoformat()
        buffer, saved = [], 0

        async def flush():
            nonlocal buffer, saved
            if not buffer:
                return saved
            rows, buffer = buffer, []
            saved += await asyncio.to_thread(save_crawl_pages, rows)
            return saved

        try:
            async for ev in deep_crawl_stream(seed, depth, pages):
                if ev.get("type") == "node":
                    text = ev.pop("_text", "")
                    if save and ev.get("is_article") and text:
                        buffer.append(
                            {
                                "crawl_id": crawl_id,
                                "url": ev["url"],
                                "source": ev.get("source"),
                                "seed": seed,
                                "title": ev.get("title"),
                                "text": text,
                                "words": ev.get("words"),
                                "depth": ev.get("depth"),
                                "fetched_at": fetched_at,
                            }
                        )
                        if len(buffer) >= 50:
                            s = await flush()
                            yield f"data: {json.dumps({'type': 'saved', 'count': s})}\n\n"
                    yield f"data: {json.dumps(ev)}\n\n"
                elif ev.get("type") == "done":
                    if save:
                        s = await flush()
                        ev["stats"]["saved"] = s
                        yield f"data: {json.dumps({'type': 'saved', 'count': s})}\n\n"
                    yield f"data: {json.dumps(ev)}\n\n"
                else:
                    yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/api/articles")
def delete_articles():
    """Delete all stored articles from Postgres."""
    from store import delete_all_articles

    deleted = delete_all_articles()
    if not deleted:
        detail = "Check database connection settings."
        return {
            "error": "Unable to delete articles.",
            "detail": detail,
        }
    return {"ok": True}


@app.get("/api/crawl-count")
def get_crawl_count():
    try:
        from db import fetch_one

        row = fetch_one("select count(*)::int as crawl_count from crawl_pages")
        return {"crawl_count": int((row or {}).get("crawl_count") or 0)}
    except Exception:
        return {"crawl_count": 0}


@app.get("/api/brand-sentiment")
def brand_sentiment(limit: int = 50):
    return get_brand_sentiment_rollup(limit=limit)


@app.post("/api/chat")
async def chat(payload: dict):
    """Intelligence Copilot -> DeepSeek over the filtered articles."""
    question = str(payload.get("question", "")).strip()[:2000]
    if not question:
        return {"error": "Empty question"}
    articles = (payload.get("articles") or [])[:80]
    total = int(payload.get("total") or len(articles))
    event = payload.get("event") if isinstance(payload, dict) else None
    if not isinstance(event, dict):
        event_id = payload.get("event_id") if isinstance(payload, dict) else None
        try:
            event_id = int(event_id) if event_id is not None else None
        except Exception:
            event_id = None
        event = None
        if event_id is not None:
            events = list_events()
            event = next((item for item in events if int(item.get("id") or -1) == event_id), None)

    event_context = _format_event_context(event)

    context = "\n".join(
        f"{i + 1}. [{a.get('source', '?')} | {a.get('sentiment', 'neutral')} | "
        f"{a.get('article_category') or a.get('category', 'general_article')} | score {a.get('relevance_score', '?')}] "
        f"{a.get('title', '')}\n   {a.get('summary', '') or (a.get('insight_json') or {}).get('summary', '')}"
        for i, a in enumerate(articles)
    )
    user_prompt = (
        (f"Event context:\n{event_context}\n\n" if event_context else "")
        + f"There are {total} articles in the current view.\n\n"
        + "Use the event context as background when interpreting sentiment, tone, and relevance.\n\n"
        + f"{context or '(none)'}\n\nQuestion: {question}"
    )

    try:
        reply = chat_completion(
            messages=[
                {"role": "system", "content": COPILOT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=700,
            timeout=60,
        )
        return {"reply": reply}
    except Exception as e:
        return {"error": f"LLM request failed: {e}"}
