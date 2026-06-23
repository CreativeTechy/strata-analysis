"""FastAPI service that orchestrates the pipeline.

The four stages live in their own modules:
  scraper  -> carnews/spiders/carnews_rss.py (Scrapy)
  enricher -> enrich.py
  saver    -> store.py

This API triggers the jobs and exposes configured feeds to the dashboard.
"""

import asyncio
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import BackgroundTasks, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import config
from feeds_store import bootstrap_feeds, create_feed, delete_feed, diagnose_feed_setup, update_feed

BASE_DIR = Path(__file__).resolve().parent

COPILOT_SYSTEM_PROMPT = (
    "You are Strata Intelligence Copilot, an analyst for automotive news. You "
    "receive a set of scraped articles (title, source, sentiment, category, "
    "summary). Answer using ONLY these articles, and never contradict the stated "
    "article count.\n\n"
    "DEFAULT: keep it short and high-signal - a scannable overview, ~120-180 "
    "words. For a general question, reply with: **Takeaway** (one sentence), "
    "**Mood** (sentiment split + tone), **Negatives** (1-2 sentences), "
    "**Positives** (1-2 sentences), and **Common threads** (1-3 short bullets, or "
    "what stands out if there's no clear pattern). Use light Markdown. Do NOT "
    "list every article, cite 'Article N', or open with 'Based on the N "
    "articles'.\n\n"
    "DEEP DIVE: only when the user explicitly asks to go deeper / expand / give "
    "details / draft a full report - then give the longer structured breakdown "
    "with evidence and specific models/brands.\n\n"
    "Always format with clean Markdown."
)

app = FastAPI(title="Strata Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def run_scraper_pipeline():
    """Scrape -> enrich -> save. enrich.py performs the Supabase upsert."""
    try:
        print("1. Scraping (carnews_rss)...")
        subprocess.run(
            ["scrapy", "crawl", "carnews_rss", "-O", "articles.json"],
            cwd=BASE_DIR,
            check=True,
        )
        print("2. Enriching + saving...")
        subprocess.run([sys.executable, "enrich.py"], cwd=BASE_DIR, check=True)
        print("Pipeline complete!")
    except subprocess.CalledProcessError as e:
        print(f"Pipeline failed: {e}")


@app.get("/")
def root():
    return {"service": "Strata Spider API", "ok": True, "see": "/api/health"}


@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "Strata Scraper API"}


@app.get("/api/feeds")
def get_feeds():
    """Configured sources for the dashboard sidebar."""
    feeds = bootstrap_feeds()
    source = feeds[0].get("source", "fallback") if feeds else "fallback"
    return {"feeds": feeds, "source": source}


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


@app.post("/scrape")
def trigger_scrape(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scraper_pipeline)
    return {"message": "Scraper pipeline triggered. It will upload to Supabase when finished."}


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

    context = "\n".join(
        f"{i + 1}. [{a.get('source', '?')} | {a.get('sentiment', 'neutral')} | "
        f"{a.get('category', 'other')} | score {a.get('relevance_score', '?')}] "
        f"{a.get('title', '')}\n   {a.get('summary', '')}"
        for i, a in enumerate(articles)
    )
    user_prompt = (
        f"There are {total} articles in the current view.\n\n"
        f"{context or '(none)'}\n\nQuestion: {question}"
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
