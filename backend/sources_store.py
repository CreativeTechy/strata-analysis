"""Postgres-backed source management helpers."""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urlparse

import config
import db
from projects_store import set_source_projects, list_source_project_ids


SOURCE_SELECT = "id,url,name,enabled,source_type,limited,created_at,updated_at"

TERM_SOURCE_TYPES = {"username", "hashtag", "keyword"}


def _default_name(url):
    if not url:
        return "Source"
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
        # Use the RSS search endpoint, not the HTML search UI
        # (news.google.com/search). The HTML page is meant for a logged-in
        # browser and frequently serves a cookie/consent interstitial instead
        # of results when scraped, which used to get saved as a fake article
        # ("Before you continue to Google", "Personalization settings &
        # cookies" - see content_guard.py). The RSS feed returns real
        # <item><link> entries that redirect straight to the publisher
        # article, and the spider parses feed-like responses as a feed
        # regardless of source_type, so keyword sources are crawled the same
        # way as any other RSS source.
        return f"https://news.google.com/rss/search?q={quote_plus(text)}"
    return ""


def _normalize_record(row, include_project_ids=False):
    url = (row.get("url") or "").strip()
    name = (row.get("name") or "").strip() or _default_name(url)
    source_type = config._resolve_source_type(row.get("source_type") or "", url)
    return {
        "id": row.get("id"),
        "url": url,
        "name": name,
        "enabled": bool(row.get("enabled", True)),
        "source_type": source_type,
        "limited": bool(row.get("limited", False)),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "source": row.get("source", "database"),
        "project_ids": list_source_project_ids(row.get("id")) if include_project_ids and row.get("id") else [],
    }


def _upsert_payload(source):
    if isinstance(source, str):
        source = {"url": source}
    elif not isinstance(source, dict):
        source = {}

    raw_url = source.get("url") or source.get("additionalProp1") or source.get("value") or ""
    url = str(raw_url).strip()
    name = (source.get("name") or "").strip()
    source_type_input = str(source.get("source_type") or "").strip().lower()

    if not url and source_type_input in TERM_SOURCE_TYPES and name:
        url = _derive_term_url(source_type_input, name)

    source_type = config._resolve_source_type(source_type_input, url)
    return {
        "url": url,
        "name": name or _default_name(url),
        "enabled": bool(source.get("enabled", True)),
        "source_type": source_type,
        "limited": bool(source.get("limited", False)),
    }


def _fetch_source_by_url(url):
    if not url or not config.DATABASE_URL:
        return None
    row = db.fetch_one(f"select {SOURCE_SELECT} from sources where url = %s limit 1", (url,))
    return _normalize_record({**row, "source": "database"}) if row else None


def _fetch_source_by_id(source_id):
    if not config.DATABASE_URL:
        return None
    row = db.fetch_one(f"select {SOURCE_SELECT} from sources where id = %s limit 1", (source_id,))
    return _normalize_record({**row, "source": "database"}) if row else None


def _fallback_records():
    return []


def list_sources_page(limit=25, offset=0):
    if not config.DATABASE_URL:
        return {"sources": _fallback_records(), "total": 0, "limit": int(limit or 0), "offset": int(offset or 0)}

    limit = max(1, min(int(limit or 25), 100))
    offset = max(0, int(offset or 0))

    try:
        rows = db.fetch_all(
            f"""
            select {SOURCE_SELECT}
            from sources
            order by created_at asc
            limit %s offset %s
            """,
            (limit, offset),
        )
        count_row = db.fetch_one("select count(*)::int as total from sources")
        sources = [_normalize_record({**row, "source": "database"}) for row in rows]
        return {
            "sources": sources,
            "total": int((count_row or {}).get("total") or len(sources)),
            "limit": limit,
            "offset": offset,
        }
    except Exception:
        return {"sources": _fallback_records(), "total": 0, "limit": limit, "offset": offset}


def bootstrap_sources():
    if not config.DATABASE_URL:
        return []
    try:
        rows = db.fetch_all(
            f"""
            select {SOURCE_SELECT}
            from sources
            order by created_at asc
            """
        )
        return [_normalize_record({**row, "source": "database"}) for row in rows]
    except Exception:
        return []


def create_source(source):
    if not config.DATABASE_URL:
        return None

    payload = _upsert_payload(source)
    project_ids = source.get("project_ids") or [] if isinstance(source, dict) else []
    if not payload["url"]:
        return None

    try:
        row = db.fetch_one(
            f"""
            insert into sources (url, name, enabled, source_type, limited)
            values (%s, %s, %s, %s, %s)
            on conflict (url) do update set
              name = excluded.name,
              enabled = excluded.enabled,
              source_type = excluded.source_type,
              limited = excluded.limited,
              updated_at = now()
            returning {SOURCE_SELECT}
            """,
            (
                payload["url"],
                payload["name"],
                payload["enabled"],
                payload["source_type"],
                payload["limited"],
            ),
        )
        if not row:
            return None
        record = _normalize_record({**row, "source": "database"})
        if project_ids is not None:
            record["project_ids"] = set_source_projects(record["id"], project_ids)
        return record
    except Exception:
        return None


def update_source(source_id, source):
    if not config.DATABASE_URL:
        return None

    payload = _upsert_payload(source)
    project_ids = source.get("project_ids") if isinstance(source, dict) else None

    try:
        row = db.fetch_one(
            f"""
            update sources
            set url = %s,
                name = %s,
                enabled = %s,
                source_type = %s,
                limited = %s,
                updated_at = now()
            where id = %s
            returning {SOURCE_SELECT}
            """,
            (
                payload["url"],
                payload["name"],
                payload["enabled"],
                payload["source_type"],
                payload["limited"],
                source_id,
            ),
        )
        if not row:
            return None
        record = _normalize_record({**row, "source": "database"})
        if project_ids is not None:
            record["project_ids"] = set_source_projects(record["id"], project_ids)
        return record
    except Exception:
        return None


def delete_source(source_id):
    if not config.DATABASE_URL:
        return False
    try:
        db.execute("delete from sources where id = %s", (source_id,))
        return True
    except Exception:
        return False


def diagnose_source_setup():
    if not config.DATABASE_URL:
        return "DATABASE_URL is missing."

    try:
        row = db.fetch_one("select 1 as ok")
        if not row:
            return "Database request failed."
        return ""
    except Exception as e:
        return f"Database request failed: {e}"
