"""Read helpers for the articles table.

These helpers keep the Supabase REST query shape in one place so the API can
offer stable pagination and filtering without the dashboard talking to Supabase
directly.
"""

from __future__ import annotations

import requests

import config
from events_store import list_article_ids_for_event

ARTICLES_SELECT = (
    "id,url,source,feed,title,author,published,text,fetched_at,summary,"
    "sentiment,relevance_score,category,organizations,entities,topics,key_points,"
    "risks,opportunities,brands,car_models,created_at"
)

SORTABLE_COLUMNS = {
    "published",
    "relevance_score",
    "created_at",
    "title",
    "source",
    "category",
    "sentiment",
}

MAX_LIMIT = 100
DEFAULT_LIMIT = 24
DEFAULT_SORT = "published.desc"


def _auth_headers():
    return {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Accept": "application/json",
    }


def _base_endpoint():
    return f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/articles"


def _parse_total(content_range: str | None, fallback: int = 0) -> int:
    if not content_range or "/" not in content_range:
        return fallback
    try:
        total = content_range.rsplit("/", 1)[-1]
        return int(total) if total != "*" else fallback
    except Exception:
        return fallback


def _normalize_text(value: str | None) -> str:
    return (value or "").strip()


def _normalize_sentiment(value: str | None) -> str:
    return _normalize_text(value).lower()


def _normalize_category(value: str | None) -> str:
    return _normalize_text(value).lower()


def _normalize_limit(value, default=DEFAULT_LIMIT):
    try:
        limit = int(value)
    except Exception:
        limit = default
    return max(1, min(limit, MAX_LIMIT))


def _normalize_offset(value):
    try:
        offset = int(value)
    except Exception:
        offset = 0
    return max(0, offset)


def _normalize_sort(value: str | None):
    raw = _normalize_text(value) or DEFAULT_SORT
    direction = "desc"
    field = raw

    if raw.startswith("-"):
        field = raw[1:]
        direction = "desc"
    elif "." in raw:
        parts = raw.split(".", 1)
        field = parts[0]
        direction = parts[1] if parts[1] in {"asc", "desc"} else "desc"
    elif raw.endswith("_asc"):
        field = raw[:-4]
        direction = "asc"
    elif raw.endswith("_desc"):
        field = raw[:-5]
        direction = "desc"

    if field not in SORTABLE_COLUMNS:
        field = "published"

    return field, direction


def _apply_search(params: dict, search: str | None):
    term = _normalize_text(search)
    if not term:
        return

    # Keep the search server-side with a Supabase/PostgREST OR clause.
    escaped = term.replace(",", " ").replace("%", "").replace("*", "")
    pattern = f"%{escaped}%"
    params["or"] = ",".join(
        [
            f"title.ilike.{pattern}",
            f"summary.ilike.{pattern}",
            f"text.ilike.{pattern}",
            f"source.ilike.{pattern}",
            f"feed.ilike.{pattern}",
            f"author.ilike.{pattern}",
        ]
    )


def _apply_filters(params: dict, search=None, sentiment=None, category=None, event_id=None):
    _apply_search(params, search)

    sentiment_value = _normalize_sentiment(sentiment)
    if sentiment_value and sentiment_value != "all":
        params["sentiment"] = f"eq.{sentiment_value}"

    category_value = _normalize_category(category)
    if category_value and category_value != "all":
        params["category"] = f"eq.{category_value}"

    if event_id is not None:
        article_ids = list_article_ids_for_event(event_id)
        if not article_ids:
            params["id"] = "eq.-1"
            return
        params["id"] = f"in.({','.join(str(article_id) for article_id in article_ids)})"


def _fetch_articles(params: dict):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return [], 0

    try:
        resp = requests.get(
            _base_endpoint(),
            headers={
                **_auth_headers(),
                "Prefer": "count=exact",
            },
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list):
            rows = []
        total = _parse_total(resp.headers.get("Content-Range"), fallback=len(rows))
        return rows, total
    except Exception:
        return [], 0


def list_articles(search=None, sentiment=None, category=None, event_id=None, limit=DEFAULT_LIMIT, offset=0, sort=DEFAULT_SORT):
    limit = _normalize_limit(limit)
    offset = _normalize_offset(offset)
    field, direction = _normalize_sort(sort)

    params = {
        "select": ARTICLES_SELECT,
        "limit": str(limit),
        "offset": str(offset),
        "order": f"{field}.{direction}",
    }
    _apply_filters(params, search=search, sentiment=sentiment, category=category, event_id=event_id)
    rows, total = _fetch_articles(params)
    return {
        "articles": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": f"{field}.{direction}",
    }


def _count_articles(search=None, sentiment=None, category=None, event_id=None):
    params = {
        "select": "id",
        "limit": "1",
    }
    _apply_filters(params, search=search, sentiment=sentiment, category=category, event_id=event_id)
    _, total = _fetch_articles(params)
    return total


def get_article_stats(search=None, category=None, event_id=None):
    total = _count_articles(search=search, category=category, event_id=event_id)
    positive = _count_articles(search=search, sentiment="positive", category=category, event_id=event_id)
    negative = _count_articles(search=search, sentiment="negative", category=category, event_id=event_id)
    neutral = _count_articles(search=search, sentiment="neutral", category=category, event_id=event_id)

    return {
        "total": total,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
    }
