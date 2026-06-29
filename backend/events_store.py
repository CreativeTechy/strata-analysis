"""Supabase-backed event helpers.

Events group feeds and articles for a single scrape scope. Feeds can be shared
across events, so memberships live in a join table.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

import requests

import config


def _headers():
    return {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _endpoint():
    return f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/events"


def _event_feeds_endpoint():
    return f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/event_feeds"


def _article_events_endpoint():
    return f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/article_events"


def _feeds_endpoint():
    return f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/feeds"


def _clean_ids(values: Iterable) -> list[int]:
    cleaned = []
    seen = set()
    for value in values or []:
        try:
            item = int(value)
        except Exception:
            continue
        if item not in seen:
            seen.add(item)
            cleaned.append(item)
    return cleaned


def _clean_terms(values: Iterable) -> list[str]:
    cleaned = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _response_error(resp):
    body = (resp.text or "").strip()
    if body:
        return f"HTTP {resp.status_code}: {body}"
    return f"HTTP {resp.status_code}"


def _normalize_event(row, feed_ids=None):
    hashtags = row.get("hashtags") or []
    keywords = row.get("keywords") or []
    if isinstance(hashtags, str):
        hashtags = [hashtags]
    if isinstance(keywords, str):
        keywords = [keywords]
    return {
        "id": row.get("id"),
        "name": (row.get("name") or "").strip(),
        "status": (row.get("status") or "draft").strip().lower() or "draft",
        "description": (row.get("description") or "").strip(),
        "location": (row.get("location") or "").strip(),
        "target_audience": (row.get("target_audience") or "").strip(),
        "hashtags": _clean_terms(hashtags),
        "keywords": _clean_terms(keywords),
        "start_date": row.get("start_date"),
        "end_date": row.get("end_date"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "feed_ids": _clean_ids(feed_ids or []),
    }


def _normalize_feed(row):
    url = (row.get("url") or "").strip()
    name = (row.get("name") or "").strip() or url
    inferred_type = config._infer_source_type(url)
    source_type = (row.get("source_type") or inferred_type or "rss").strip().lower() or "rss"
    if inferred_type == "social":
        source_type = "social"
    return {
        "id": row.get("id"),
        "url": url,
        "name": name,
        "enabled": bool(row.get("enabled", True)),
        "source_type": source_type,
        "category": (row.get("category") or "").strip(),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _fetch_rows(endpoint, params):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []
    resp = requests.get(endpoint, headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    rows = resp.json()
    return rows if isinstance(rows, list) else []


def _fetch_event_feed_map():
    rows = _fetch_rows(
        _event_feeds_endpoint(),
        {"select": "event_id,feed_id", "order": "event_id.asc,feed_id.asc"},
    )
    mapping = defaultdict(list)
    for row in rows:
        try:
            event_id = int(row.get("event_id"))
            feed_id = int(row.get("feed_id"))
        except Exception:
            continue
        mapping[event_id].append(feed_id)
    return mapping


def _fetch_feed_event_map():
    rows = _fetch_rows(
        _event_feeds_endpoint(),
        {"select": "event_id,feed_id", "order": "feed_id.asc,event_id.asc"},
    )
    mapping = defaultdict(list)
    for row in rows:
        try:
            event_id = int(row.get("event_id"))
            feed_id = int(row.get("feed_id"))
        except Exception:
            continue
        mapping[feed_id].append(event_id)
    return mapping


def _fetch_article_event_map(event_id):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []
    try:
        rows = _fetch_rows(
            _article_events_endpoint(),
            {
                "select": "article_id",
                "event_id": f"eq.{int(event_id)}",
                "order": "article_id.asc",
            },
        )
    except Exception:
        return []
    ids = []
    seen = set()
    for row in rows:
        try:
            article_id = int(row.get("article_id"))
        except Exception:
            continue
        if article_id not in seen:
            seen.add(article_id)
            ids.append(article_id)
    return ids


def _upsert_rows(endpoint, rows, conflict_key, *, prefer="resolution=merge-duplicates,return=representation"):
    if not rows or not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []

    resp = requests.post(
        f"{endpoint}?on_conflict={conflict_key}",
        headers={**_headers(), "Prefer": prefer},
        json=rows,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json() if resp.content else None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def list_events():
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []

    try:
        rows = _fetch_rows(
            _endpoint(),
            {
                "select": "id,name,status,description,location,target_audience,hashtags,keywords,start_date,end_date,created_at,updated_at",
                "order": "created_at.asc",
            },
        )
        feed_map = _fetch_event_feed_map()
        return [_normalize_event(row, feed_map.get(row.get("id"), [])) for row in rows]
    except Exception:
        return []


def get_event(event_id):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return None

    try:
        rows = _fetch_rows(
            _endpoint(),
            {
                "select": "id,name,status,description,location,target_audience,hashtags,keywords,start_date,end_date,created_at,updated_at",
                "id": f"eq.{int(event_id)}",
                "limit": 1,
            },
        )
        if not rows:
            return None
        feed_map = _fetch_event_feed_map()
        return _normalize_event(rows[0], feed_map.get(rows[0].get("id"), []))
    except Exception:
        return None


def _event_payload(event):
    if not isinstance(event, dict):
        event = {}

    hashtags = event.get("hashtags")
    keywords = event.get("keywords")
    if isinstance(hashtags, str):
        hashtags = [part.strip() for part in hashtags.replace("\n", ",").split(",")]
    if isinstance(keywords, str):
        keywords = [part.strip() for part in keywords.replace("\n", ",").split(",")]

    return {
        "name": (event.get("name") or "").strip(),
        "status": (event.get("status") or "draft").strip().lower() or "draft",
        "description": (event.get("description") or "").strip() or None,
        "location": (event.get("location") or "").strip() or None,
        "target_audience": (event.get("target_audience") or "").strip() or None,
        "hashtags": _clean_terms(hashtags or []),
        "keywords": _clean_terms(keywords or []),
        "start_date": event.get("start_date") or None,
        "end_date": event.get("end_date") or None,
    }


def create_event(event):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return None

    payload = _event_payload(event)
    if not payload["name"]:
        return None

    feed_ids = _clean_ids(event.get("feed_ids") or [])
    try:
        resp = requests.post(
            _endpoint(),
            headers={**_headers(), "Prefer": "return=representation"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json() if resp.content else None
        if isinstance(rows, list) and rows:
            row = rows[0]
        elif isinstance(rows, dict) and rows:
            row = rows
        else:
            row = None
        if row is None:
            return None
        created = _normalize_event(row)
        if feed_ids:
            created["feed_ids"] = set_event_feeds(created["id"], feed_ids)
        else:
            created["feed_ids"] = []
        return created
    except Exception:
        return None


def update_event(event_id, event):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return None

    payload = _event_payload(event)
    feed_ids = event.get("feed_ids")
    try:
        resp = requests.patch(
            _endpoint(),
            headers={**_headers(), "Prefer": "return=representation"},
            params={"id": f"eq.{int(event_id)}"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json() if resp.content else None
        row = None
        if isinstance(rows, list) and rows:
            row = rows[0]
        elif isinstance(rows, dict) and rows:
            row = rows
        if row is None:
            row = get_event(event_id)
            if row is None:
                return None
            row = row.copy()
        normalized = _normalize_event(row)
        if feed_ids is not None:
            normalized["feed_ids"] = set_event_feeds(event_id, feed_ids)
        else:
            normalized["feed_ids"] = list_event_feed_ids(event_id)
        return normalized
    except Exception:
        return None


def delete_event(event_id):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return False

    try:
        resp = requests.delete(
            _endpoint(),
            headers=_headers(),
            params={"id": f"eq.{int(event_id)}"},
            timeout=30,
        )
        resp.raise_for_status()
        return True
    except Exception:
        return False


def list_event_feed_ids(event_id):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []

    try:
        rows = _fetch_rows(
            _event_feeds_endpoint(),
            {
                "select": "feed_id",
                "event_id": f"eq.{int(event_id)}",
                "order": "feed_id.asc",
            },
        )
        ids = []
        seen = set()
        for row in rows:
            try:
                feed_id = int(row.get("feed_id"))
            except Exception:
                continue
            if feed_id not in seen:
                seen.add(feed_id)
                ids.append(feed_id)
        return ids
    except Exception:
        return []


def list_feed_event_ids(feed_id):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []

    try:
        rows = _fetch_rows(
            _event_feeds_endpoint(),
            {
                "select": "event_id",
                "feed_id": f"eq.{int(feed_id)}",
                "order": "event_id.asc",
            },
        )
        ids = []
        seen = set()
        for row in rows:
            try:
                event_id = int(row.get("event_id"))
            except Exception:
                continue
            if event_id not in seen:
                seen.add(event_id)
                ids.append(event_id)
        return ids
    except Exception:
        return []


def set_event_feeds(event_id, feed_ids):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []

    event_id = int(event_id)
    feed_ids = _clean_ids(feed_ids)
    try:
        requests.delete(
            _event_feeds_endpoint(),
            headers=_headers(),
            params={"event_id": f"eq.{event_id}"},
            timeout=30,
        ).raise_for_status()
    except Exception:
        return []

    if not feed_ids:
        return []

    payload = [{"event_id": event_id, "feed_id": feed_id} for feed_id in feed_ids]
    try:
        _upsert_rows(_event_feeds_endpoint(), payload, "event_id,feed_id", prefer="resolution=ignore-duplicates,return=representation")
        return feed_ids
    except Exception:
        return []


def set_feed_events(feed_id, event_ids):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []

    feed_id = int(feed_id)
    event_ids = _clean_ids(event_ids)
    try:
        requests.delete(
            _event_feeds_endpoint(),
            headers=_headers(),
            params={"feed_id": f"eq.{feed_id}"},
            timeout=30,
        ).raise_for_status()
    except Exception:
        return []

    if not event_ids:
        return []

    payload = [{"event_id": event_id, "feed_id": feed_id} for event_id in event_ids]
    try:
        _upsert_rows(_event_feeds_endpoint(), payload, "event_id,feed_id", prefer="resolution=ignore-duplicates,return=representation")
        return event_ids
    except Exception:
        return []


def list_feeds_for_event(event_id):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []

    feed_ids = list_event_feed_ids(event_id)
    if not feed_ids:
        return []

    try:
        rows = _fetch_rows(
            _feeds_endpoint(),
            {
                "select": "id,url,name,enabled,source_type,category,created_at,updated_at",
                "id": f"in.({','.join(str(feed_id) for feed_id in feed_ids)})",
                "order": "created_at.asc",
            },
        )
        return [_normalize_feed(row) for row in rows]
    except Exception:
        return []


def set_article_events(article_ids, event_id):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return 0

    article_ids = _clean_ids(article_ids)
    if not article_ids:
        return 0

    event_id = int(event_id)
    payload = [{"article_id": article_id, "event_id": event_id} for article_id in article_ids]

    try:
        _upsert_rows(
            _article_events_endpoint(),
            payload,
            "article_id,event_id",
            prefer="resolution=ignore-duplicates,return=representation",
        )
        return len(article_ids)
    except Exception:
        return 0


def list_article_ids_for_event(event_id):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []
    return _fetch_article_event_map(event_id)


def diagnose_event_setup():
    if not config.SUPABASE_URL:
        return "SUPABASE_URL is missing."
    if not config.SUPABASE_SERVICE_KEY:
        return "SUPABASE_SERVICE_KEY is missing."

    try:
        resp = requests.get(
            _endpoint(),
            headers=_headers(),
            params={"select": "id", "limit": 1},
            timeout=15,
        )
        if not resp.ok:
            return f"Supabase request failed: {_response_error(resp)}"
        return ""
    except Exception as e:
        return f"Supabase request failed: {e}"
