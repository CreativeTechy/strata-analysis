"""FastAPI service that orchestrates the pipeline.

The four stages live in their own modules:
  scraper  -> scraper/spiders/source_rss.py (Scrapy)
  enricher -> enrich.py
  saver    -> store.py

This API triggers the jobs and exposes configured feeds to the dashboard.
"""

import asyncio
import json
import os
import subprocess
import sys
import uuid
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import config
from event_discovery import discover_event_links
from articles_store import get_article_stats, list_articles
from events_store import (
    create_event,
    delete_event,
    diagnose_event_setup,
    list_events,
    list_events_page,
    list_feeds_for_event,
    set_event_feeds,
    update_event,
)
from feeds_store import bootstrap_feeds, create_feed, delete_feed, diagnose_feed_setup, list_feeds_page, update_feed
from pipeline_runs import create_pipeline_run, list_pipeline_runs, update_pipeline_run

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


def _load_pipeline_stats(stats_file: Path):
    if not stats_file.exists():
        return {}
    try:
        return json.loads(stats_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


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

    description = (event.get("description") or "").strip()
    if description:
        parts.append(f"Description: {description}")

    return "\n".join(parts)


def run_scraper_pipeline(run_id: str, event_id: int | None = None):
    """Scrape -> enrich -> save. enrich.py performs the Supabase upsert."""
    env = os.environ.copy()
    env["PIPELINE_RUN_ID"] = run_id
    if event_id is not None:
        env["PIPELINE_EVENT_ID"] = str(event_id)
    with tempfile.TemporaryDirectory(prefix=f"run-{run_id}-", dir=STORAGE_DIR) as run_dir:
        run_path = Path(run_dir)
        raw_file = run_path / "articles.raw.json"
        enriched_file = run_path / "articles.enriched.json"
        stats_file = run_path / "pipeline.stats.json"
        env["PIPELINE_WORKDIR"] = str(run_path)
        env["PIPELINE_RAW_FILE"] = str(raw_file)
        env["PIPELINE_ENRICHED_FILE"] = str(enriched_file)
        env["PIPELINE_STATS_FILE"] = str(stats_file)

        if event_id is not None:
            try:
                feeds = list_feeds_for_event(event_id)
                feed_urls = [feed.get("url") for feed in feeds if feed.get("url")]
                if feed_urls:
                    env["FEEDS"] = ",".join(feed_urls)
                else:
                    update_pipeline_run(
                        run_id,
                        status="failed",
                        stage="error",
                        message="Selected event has no feeds assigned.",
                        error="No feeds assigned to the selected event.",
                        finished_at=datetime.now(timezone.utc).isoformat(),
                    )
                    return
            except Exception:
                pass

        try:
            update_pipeline_run(run_id, status="running", stage="scrape", message="Starting scrape...")
            print("1. Scraping configured sources...")
            subprocess.run(
                ["scrapy", "crawl", "source_rss", "-O", str(raw_file)],
                cwd=BASE_DIR,
                check=True,
                env=env,
            )
            update_pipeline_run(run_id, stage="enrich", message="Scrape complete. Enriching articles...")
            print("2. Enriching + saving...")
            subprocess.run([sys.executable, "enrich.py"], cwd=BASE_DIR, check=True, env=env)
            stats = _load_pipeline_stats(stats_file)
            update_pipeline_run(
                run_id,
                status="success",
                stage="done",
                message="Pipeline complete.",
                articles_scraped=int(stats.get("articles_scraped") or 0),
                articles_cleaned=int(stats.get("articles_cleaned") or 0),
                articles_saved=int(stats.get("articles_saved") or 0),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            print("Pipeline complete!")
        except subprocess.CalledProcessError as e:
            update_pipeline_run(
                run_id,
                status="failed",
                stage="error",
                message="Pipeline failed.",
                error=str(e),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            print(f"Pipeline failed: {e}")
        except Exception as e:
            update_pipeline_run(
                run_id,
                status="failed",
                stage="error",
                message="Pipeline crashed.",
                error=str(e),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            print(f"Pipeline crashed: {e}")


@app.get("/")
def root():
    return {"service": "Strata Spider API", "ok": True, "see": "/api/health"}


@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "Strata Scraper API"}


@app.get("/api/feeds")
def get_feeds(limit: int | None = None, offset: int = 0):
    """Configured sources for the dashboard sidebar."""
    if limit is None:
        feeds = bootstrap_feeds()
        source = feeds[0].get("source", "supabase") if feeds else "supabase"
        return {"feeds": feeds, "source": source}

    page = list_feeds_page(limit=limit, offset=offset)
    source = page["feeds"][0].get("source", "supabase") if page["feeds"] else "supabase"
    return {**page, "source": source}


@app.get("/api/events")
def get_events(limit: int | None = None, offset: int = 0):
    if limit is None:
        return {"events": list_events()}
    return list_events_page(limit=limit, offset=offset)


def _default_discovery_result(event):
    feed_ids = []
    for value in event.get("feed_ids") or []:
        try:
            feed_ids.append(int(value))
        except Exception:
            continue
    return {
        "search_terms": [],
        "candidates": [],
        "suggested_links": [],
        "feed_ids": feed_ids,
        "feeds": [],
    }


def _save_event_with_discovery(event):
    if not isinstance(event, dict):
        return None, {}

    discovery = (
        discover_event_links(event)
        if (event.get("hashtags") or event.get("keywords"))
        else _default_discovery_result(event)
    )
    if discovery.get("feed_ids") is not None:
        event = {**event, "feed_ids": discovery.get("feed_ids") or event.get("feed_ids") or []}
    return event, discovery


@app.post("/api/events")
def add_event(payload: dict):
    event = create_event(payload or {})
    if not event:
        detail = diagnose_event_setup()
        return {
            "error": "Unable to create event. Check Supabase credentials and URL.",
            "detail": detail or "The event request did not return a row.",
        }
    event, discovery = _save_event_with_discovery(event)
    return {"event": event, "discovery": discovery}


@app.put("/api/events/{event_id}")
def edit_event(event_id: int, payload: dict):
    event = update_event(event_id, payload or {})
    if not event:
        detail = diagnose_event_setup()
        return {
            "error": "Unable to update event. Check Supabase credentials and URL.",
            "detail": detail or "The update request did not return a row.",
        }
    event, discovery = _save_event_with_discovery(event)
    return {"event": event, "discovery": discovery}


@app.delete("/api/events/{event_id}")
def remove_event(event_id: int):
    if not delete_event(event_id):
        detail = diagnose_event_setup()
        return {
            "error": "Unable to delete event. Check Supabase credentials and URL.",
            "detail": detail or "The delete request failed.",
        }
    return {"ok": True}


@app.get("/api/pipeline-runs")
def get_pipeline_runs(limit: int = 10):
    return {"runs": list_pipeline_runs(limit=max(1, min(int(limit), 25)))}


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


@app.post("/api/feeds")
def add_feed(payload: dict):
    """Create or update a feed record in Supabase."""
    feed = create_feed(payload or {})
    if not feed:
        detail = diagnose_feed_setup()
        return {
            "error": "Unable to create feed. Check Supabase credentials and URL.",
            "detail": detail or "The feed request did not return a row.",
        }
    return {"feed": feed}


@app.put("/api/feeds/{feed_id}")
def edit_feed(feed_id: int, payload: dict):
    """Update a feed record in Supabase."""
    feed = update_feed(feed_id, payload or {})
    if not feed:
        detail = diagnose_feed_setup()
        return {
            "error": "Unable to update feed. Check Supabase credentials and URL.",
            "detail": detail or "The update request did not return a row.",
        }
    return {"feed": feed}


@app.delete("/api/feeds/{feed_id}")
def remove_feed(feed_id: int):
    """Delete a feed record from Supabase."""
    if not delete_feed(feed_id):
        detail = diagnose_feed_setup()
        return {
            "error": "Unable to delete feed. Check Supabase credentials and URL.",
            "detail": detail or "The delete request failed.",
        }
    return {"ok": True}


@app.post("/api/events/{event_id}/feeds")
def replace_event_feeds(event_id: int, payload: dict):
    feed_ids = payload.get("feed_ids") if isinstance(payload, dict) else []
    assigned = set_event_feeds(event_id, feed_ids or [])
    return {"event_id": event_id, "feed_ids": assigned}


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

    if not list_feeds_for_event(event_id):
        raise HTTPException(status_code=400, detail="Assign at least one feed to the selected event before scraping.")

    run = create_pipeline_run(status="queued", stage="queued", message="Queued for execution.", event_id=event_id)
    run_id = run["id"] if run else uuid.uuid4().hex
    background_tasks.add_task(run_scraper_pipeline, run_id, event_id)
    return {
        "message": "Scraper pipeline triggered. It will upload to Supabase when finished.",
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
    """Delete all stored articles from Supabase."""
    from store import delete_all_articles

    deleted = delete_all_articles()
    if not deleted:
        detail = "Check Supabase credentials and URL."
        return {
            "error": "Unable to delete articles.",
            "detail": detail,
        }
    return {"ok": True}


@app.post("/api/chat")
async def chat(payload: dict):
    """Intelligence Copilot -> DeepSeek over the filtered articles."""
    if not config.DEEPSEEK_API_KEY:
        return {"error": "DEEPSEEK_API_KEY not set"}

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
        resp = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"},
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": COPILOT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 700,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return {"reply": resp.json()["choices"][0]["message"]["content"].strip()}
    except Exception as e:
        return {"error": f"DeepSeek request failed: {e}"}
