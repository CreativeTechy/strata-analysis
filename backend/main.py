"""FastAPI service that orchestrates the pipeline.

The four stages live in their own modules:
  scraper  -> carnews/spiders/carnews_rss.py (Scrapy)
  enricher -> enrich.py
  saver    -> store.py

This API only triggers them and exposes the configured feeds to the dashboard.
"""

import asyncio
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import config
from config import load_feeds

BASE_DIR = Path(__file__).resolve().parent

COPILOT_SYSTEM_PROMPT = (
    "You are Strata Intelligence Copilot, an analyst for automotive news. You "
    "receive a set of scraped articles (title, source, sentiment, category, "
    "summary). Answer using ONLY these articles, and never contradict the stated "
    "article count.\n\n"
    "DEFAULT: keep it short and high-signal — a scannable overview, ~120-180 "
    "words. For a general question, reply with: **Takeaway** (one sentence), "
    "**Mood** (sentiment split + tone), **Negatives** (1-2 sentences), "
    "**Positives** (1-2 sentences), and **Common threads** (1-3 short bullets, or "
    "what stands out if there's no clear pattern). Use light Markdown. Do NOT "
    "list every article, cite 'Article N', or open with 'Based on the N "
    "articles'.\n\n"
    "DEEP DIVE: only when the user explicitly asks to go deeper / expand / give "
    "details / draft a full report — then give the longer structured breakdown "
    "with evidence and specific models/brands.\n\n"
    "Always format with clean Markdown."
)

app = FastAPI(title="Strata Scraper API")

# Allow the dashboard to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def run_scraper_pipeline():
    """scrape -> enrich -> save. enrich.py performs the Supabase upsert."""
    try:
        print("1. Scraping (carnews_rss)...")
        subprocess.run(
            ["scrapy", "crawl", "carnews_rss", "-O", "articles.json"],
            cwd=BASE_DIR, check=True,
        )
        print("2. Enriching + saving...")
        subprocess.run(["python", "enrich.py"], cwd=BASE_DIR, check=True)
        print("🎉 Pipeline complete!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Pipeline failed: {e}")


@app.get("/")
def root():
    # Root 200 so platform health probes (e.g. HF Spaces) report "Running".
    return {"service": "Strata Spider API", "ok": True, "see": "/api/health"}


@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "Strata Scraper API"}


@app.get("/api/feeds")
def get_feeds():
    """Configured sources — single source of truth for the dashboard sidebar."""
    return {"feeds": load_feeds()}


@app.post("/scrape")
def trigger_scrape(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scraper_pipeline)
    return {"message": "Scraper pipeline triggered. It will upload to Supabase when finished."}


@app.get("/api/spider/stream")
async def spider_stream(seed: str, depth: int = 2, pages: int = 300, save: int = 0):
    """Server-Sent Events: live deep crawl for the Spider Mode page.

    Streams one event per discovered page (for the graph) and a final stats
    event. With save=1, article pages are upserted into `crawl_pages` in batches
    as the crawl runs (full text persisted server-side; never sent to the
    browser). Engine import is lazy so the API works without crawl4ai.
    """
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
                    text = ev.pop("_text", "")  # strip server-only text
                    if save and ev.get("is_article") and text:
                        buffer.append({
                            "crawl_id": crawl_id, "url": ev["url"], "source": ev.get("source"),
                            "seed": seed, "title": ev.get("title"), "text": text,
                            "words": ev.get("words"), "depth": ev.get("depth"),
                            "fetched_at": fetched_at,
                        })
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
    """Intelligence Copilot -> DeepSeek over the filtered articles (local-dev
    parity with the Cloudflare Worker)."""
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
    system_prompt = COPILOT_SYSTEM_PROMPT
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
                    {"role": "system", "content": system_prompt},
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
