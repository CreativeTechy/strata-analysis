"""The SAVER stage: the single Supabase upsert path for enriched articles.

Both the API (main.py) and the CI run go through here, so there is exactly one
place that writes to the database. Upserts on `url` (merge-duplicates), so
re-seeing an article from a feed updates it in place instead of duplicating.
"""

import requests
from collections import defaultdict
import json

import config
from events_store import list_event_ids_for_feed_url, set_article_events

ARTICLE_COLUMNS = (
    "url", "source", "feed", "title", "author", "published", "text",
    "fetched_at", "summary", "sentiment", "relevance_score", "category",
    "article_category", "insight_json", "analysis_model", "analysis_prompt_version", "analyzed_at",
    "organizations", "entities", "topics", "key_points", "risks", "opportunities",
    "brands", "car_models",
)

LEGACY_ARTICLE_COLUMNS = (
    "url", "source", "feed", "title", "author", "published", "text",
    "fetched_at", "summary", "sentiment", "relevance_score", "category",
    "organizations", "entities", "topics", "key_points", "risks", "opportunities",
    "brands", "car_models",
)


def _row(article):
    return {k: article.get(k) for k in ARTICLE_COLUMNS}


def _legacy_row(article):
    return {k: article.get(k) for k in LEGACY_ARTICLE_COLUMNS}


def _response_snippet(resp, limit=500):
    if resp is None:
        return ""
    try:
        payload = resp.json()
        return json.dumps(payload, ensure_ascii=False)[:limit]
    except Exception:
        try:
            return (resp.text or "")[:limit]
        except Exception:
            return ""


def _log_supabase_error(prefix, error):
    resp = getattr(error, "response", None)
    status = getattr(resp, "status_code", None)
    snippet = _response_snippet(resp)
    if status is not None:
        print(f"{prefix} HTTP {status}: {error}")
    else:
        print(f"{prefix}: {error}")
    if snippet:
        print(f"  response: {snippet}")


def _probe_article_schema():
    """Check whether the new enrichment columns exist in Supabase."""
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return {"ok": False, "reason": "missing credentials"}

    headers = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Accept": "application/json",
    }
    endpoint = f"{config.SUPABASE_URL}/rest/v1/articles"
    params = {
        "select": "article_category,insight_json,analysis_model,analysis_prompt_version,analyzed_at",
        "limit": "1",
    }

    try:
        resp = requests.get(endpoint, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        return {"ok": True, "reason": "new columns available"}
    except Exception as e:
        resp = getattr(e, "response", None)
        snippet = _response_snippet(resp)
        return {
            "ok": False,
            "reason": "new columns unavailable",
            "error": str(e),
            "response": snippet,
        }


CRAWL_COLUMNS = (
    "crawl_id", "url", "source", "seed", "title", "text", "words", "depth", "fetched_at",
)


def save_crawl_pages(rows, batch_size=50):
    """Upsert raw spider pages into the `crawl_pages` table (on_conflict url).

    Returns the number of rows sent. Runs synchronously (call via a thread from
    async code). No-ops with a warning if creds are missing.
    """
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        print("Supabase credentials not set, skipping crawl save.")
        return 0

    headers = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    endpoint = f"{config.SUPABASE_URL}/rest/v1/crawl_pages?on_conflict=url"

    sent = 0
    for i in range(0, len(rows), batch_size):
        batch = [{k: r.get(k) for k in CRAWL_COLUMNS} for r in rows[i:i + batch_size]]
        try:
            resp = requests.post(endpoint, headers=headers, json=batch, timeout=30)
            resp.raise_for_status()
            sent += len(batch)
        except Exception as e:
            print(f"  crawl_pages upload error: {e}")
    return sent


def save_articles(articles, batch_size=50):
    """Upsert articles into the Supabase `articles` table.

    Returns the number of rows sent. No-ops with a warning if creds are missing.
    """
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        print("Supabase credentials not set, skipping upload.")
        return 0

    headers = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    endpoint = f"{config.SUPABASE_URL}/rest/v1/articles?on_conflict=url"
    schema_probe = _probe_article_schema()
    if not schema_probe.get("ok"):
        print(f"  articles schema probe: {schema_probe.get('reason')}")
        if schema_probe.get("response"):
            print(f"  articles schema probe response: {schema_probe.get('response')}")

    sent = 0
    event_id = None
    try:
        from os import environ

        raw_event_id = (environ.get("PIPELINE_EVENT_ID") or "").strip()
        if raw_event_id:
            event_id = int(raw_event_id)
    except Exception:
        event_id = None

    feed_event_cache = {}
    linked_articles = defaultdict(list)

    for i in range(0, len(articles), batch_size):
        source_batch = articles[i:i + batch_size]
        batch = [_row(a) for a in source_batch]
        try:
            resp = requests.post(endpoint, headers=headers, json=batch, timeout=30)
            resp.raise_for_status()
            sent += len(batch)
            rows = resp.json() if resp.content else []
            if isinstance(rows, dict):
                rows = [rows]
            if not isinstance(rows, list):
                rows = []
            if rows:
                for idx, row in enumerate(rows):
                    if not isinstance(row, dict):
                        continue
                    try:
                        article_id = int(row.get("id"))
                    except Exception:
                        continue
                    article = source_batch[idx] if idx < len(source_batch) else {}
                    feed_url = (row.get("feed") or article.get("feed") or "").strip()
                    if not feed_url:
                        continue
                    if feed_url not in feed_event_cache:
                        feed_event_cache[feed_url] = list_event_ids_for_feed_url(feed_url)
                    event_ids = list(feed_event_cache.get(feed_url) or [])
                    if event_id is not None and event_id not in event_ids:
                        event_ids.append(event_id)
                    for linked_event_id in event_ids:
                        if article_id not in linked_articles[linked_event_id]:
                            linked_articles[linked_event_id].append(article_id)
            print(f"  Uploaded batch {i // batch_size + 1} ({len(batch)} articles)")
        except Exception as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code == 400:
                try:
                    legacy_batch = [_legacy_row(a) for a in source_batch]
                    resp = requests.post(endpoint, headers=headers, json=legacy_batch, timeout=30)
                    resp.raise_for_status()
                    sent += len(legacy_batch)
                    print(
                        f"  Uploaded batch {i // batch_size + 1} ({len(legacy_batch)} articles) using legacy article schema fallback"
                    )
                    continue
                except Exception as legacy_error:
                    _log_supabase_error(f"  Supabase upload error for batch {i // batch_size + 1}", legacy_error)
                    continue
            _log_supabase_error(f"  Supabase upload error for batch {i // batch_size + 1}", e)

    if linked_articles:
        for linked_event_id, article_ids in linked_articles.items():
            set_article_events(article_ids, linked_event_id)

    return sent


def delete_all_articles():
    """Delete all rows from the Supabase `articles` table."""
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        print("Supabase credentials not set, skipping article delete.")
        return 0

    headers = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Accept": "application/json",
        "Prefer": "return=minimal",
    }
    endpoint = f"{config.SUPABASE_URL}/rest/v1/articles"

    try:
        resp = requests.delete(endpoint, headers=headers, params={"id": "gte.0"}, timeout=30)
        resp.raise_for_status()
        return 1
    except Exception as e:
        print(f"  article delete error: {e}")
        return 0
