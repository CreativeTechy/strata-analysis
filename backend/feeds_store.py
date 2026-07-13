"""Postgres-backed feed management helpers."""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urlparse

import config
import db
from events_store import set_feed_events, list_feed_event_ids


FEED_SELECT = "id,url,name,enabled,source_type,category,created_at,updated_at"

TERM_SOURCE_TYPES = {"username", "hashtag", "keyword"}


def _default_name(url):
    if not url:
        return "Feed"
    host = urlparse(url).netloc or url
    return host.removeprefix("www.")


def _derive_term_url(source_type, term):
    text = (term or "").strip()
    if not text:
        return ""
    if source_type == "username":
        handle = text.lstrip("@").split("/", 1)[0].strip()
        handle = re.sub(r"[^A-Za-z0-9_]", "", handle)
        return f"https://x.com/{handle}" if handle else ""
    if source_type == "hashtag":
        tag = text.lstrip("#").strip()
        tag = re.sub(r"[^A-Za-z0-9_]", "", tag)
        return f"https://x.com/hashtag/{tag}" if tag else ""
    if source_type == "keyword":
        return f"https://news.google.com/search?q={quote_plus(text)}"
    return ""


def _normalize_record(row, include_event_ids=False):
    url = (row.get("url") or "").strip()
    name = (row.get("name") or "").strip() or _default_name(url)
    source_type = config._resolve_source_type(row.get("source_type") or "", url)
    return {
        "id": row.get("id"),
        "url": url,
        "name": name,
        "enabled": bool(row.get("enabled", True)),
        "source_type": source_type,
        "category": row.get("category") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "source": row.get("source", "database"),
        "event_ids": list_feed_event_ids(row.get("id")) if include_event_ids and row.get("id") else [],
    }


def _upsert_payload(feed):
    if isinstance(feed, str):
        feed = {"url": feed}
    elif not isinstance(feed, dict):
        feed = {}

    raw_url = feed.get("url") or feed.get("additionalProp1") or feed.get("value") or ""
    url = str(raw_url).strip()
    name = (feed.get("name") or "").strip()
    source_type_input = str(feed.get("source_type") or "").strip().lower()

    if not url and source_type_input in TERM_SOURCE_TYPES and name:
        url = _derive_term_url(source_type_input, name)

    source_type = config._resolve_source_type(source_type_input, url)
    return {
        "url": url,
        "name": name or _default_name(url),
        "enabled": bool(feed.get("enabled", True)),
        "source_type": source_type,
        "category": (feed.get("category") or "").strip(),
    }


def _fetch_feed_by_url(url):
    if not url or not config.DATABASE_URL:
        return None
    row = db.fetch_one(f"select {FEED_SELECT} from feeds where url = %s limit 1", (url,))
    return _normalize_record({**row, "source": "database"}) if row else None


def _fetch_feed_by_id(feed_id):
    if not config.DATABASE_URL:
        return None
    row = db.fetch_one(f"select {FEED_SELECT} from feeds where id = %s limit 1", (feed_id,))
    return _normalize_record({**row, "source": "database"}) if row else None


def _fallback_records():
    return []


def list_feeds_page(limit=25, offset=0):
    if not config.DATABASE_URL:
        return {"feeds": _fallback_records(), "total": 0, "limit": int(limit or 0), "offset": int(offset or 0)}

    limit = max(1, min(int(limit or 25), 100))
    offset = max(0, int(offset or 0))

    try:
        rows = db.fetch_all(
            f"""
            select {FEED_SELECT}
            from feeds
            order by created_at asc
            limit %s offset %s
            """,
            (limit, offset),
        )
        count_row = db.fetch_one("select count(*)::int as total from feeds")
        feeds = [_normalize_record({**row, "source": "database"}) for row in rows]
        return {
            "feeds": feeds,
            "total": int((count_row or {}).get("total") or len(feeds)),
            "limit": limit,
            "offset": offset,
        }
    except Exception:
        return {"feeds": _fallback_records(), "total": 0, "limit": limit, "offset": offset}


def bootstrap_feeds():
    if not config.DATABASE_URL:
        return []
    try:
        rows = db.fetch_all(
            f"""
            select {FEED_SELECT}
            from feeds
            order by created_at asc
            """
        )
        return [_normalize_record({**row, "source": "database"}) for row in rows]
    except Exception:
        return []


def create_feed(feed):
    if not config.DATABASE_URL:
        return None

    payload = _upsert_payload(feed)
    event_ids = feed.get("event_ids") or [] if isinstance(feed, dict) else []
    if not payload["url"]:
        return None

    try:
        row = db.fetch_one(
            f"""
            insert into feeds (url, name, enabled, source_type, category)
            values (%s, %s, %s, %s, %s)
            on conflict (url) do update set
              name = excluded.name,
              enabled = excluded.enabled,
              source_type = excluded.source_type,
              category = excluded.category,
              updated_at = now()
            returning {FEED_SELECT}
            """,
            (
                payload["url"],
                payload["name"],
                payload["enabled"],
                payload["source_type"],
                payload["category"],
            ),
        )
        if not row:
            return None
        record = _normalize_record({**row, "source": "database"})
        if event_ids is not None:
            record["event_ids"] = set_feed_events(record["id"], event_ids)
        return record
    except Exception:
        return None


def update_feed(feed_id, feed):
    if not config.DATABASE_URL:
        return None

    payload = _upsert_payload(feed)
    event_ids = feed.get("event_ids") if isinstance(feed, dict) else None

    try:
        row = db.fetch_one(
            f"""
            update feeds
            set url = %s,
                name = %s,
                enabled = %s,
                source_type = %s,
                category = %s,
                updated_at = now()
            where id = %s
            returning {FEED_SELECT}
            """,
            (
                payload["url"],
                payload["name"],
                payload["enabled"],
                payload["source_type"],
                payload["category"],
                feed_id,
            ),
        )
        if not row:
            return None
        record = _normalize_record({**row, "source": "database"})
        if event_ids is not None:
            record["event_ids"] = set_feed_events(record["id"], event_ids)
        return record
    except Exception:
        return None


def delete_feed(feed_id):
    if not config.DATABASE_URL:
        return False
    try:
        db.execute("delete from feeds where id = %s", (feed_id,))
        return True
    except Exception:
        return False


def diagnose_feed_setup():
    if not config.DATABASE_URL:
        return "DATABASE_URL is missing."

    try:
        row = db.fetch_one("select 1 as ok")
        if not row:
            return "Database request failed."
        return ""
    except Exception as e:
        return f"Database request failed: {e}"

