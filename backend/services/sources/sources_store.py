"""Postgres-backed source management helpers."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, quote_plus, urlparse

import config
import db
from services.projects.projects_store import set_source_projects, list_source_project_ids


SOURCE_SELECT = "id,url,name,enabled,source_type,limited,created_at,updated_at"

TERM_SOURCE_TYPES = {"username", "hashtag", "keyword"}

REDDIT_KINDS = {"subreddit", "user", "search"}


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


def _derive_reddit_url(term, kind=None):
    """Turn a full reddit.com URL, a `r/`/`u/` prefixed short form, or a bare
    subreddit/username/search term into a canonical reddit.com URL.

    A bare term (no `r/`/`u/` prefix, not a URL) is ambiguous - it could be a
    subreddit, a username, or a search phrase (see the source-type
    requirements) - so `kind` (from the dashboard's Reddit-kind selector)
    disambiguates it. It only matters for bare terms; an explicit `r/...`,
    `u/.../user/...`, or full URL is unambiguous on its own and `kind` is
    ignored.
    """
    text = (term or "").strip()
    if not text:
        return ""

    if re.match(r"^https?://", text, re.I):
        parsed = urlparse(text)
        host = parsed.netloc.lower().removeprefix("www.")
        if host != "reddit.com" and not host.endswith(".reddit.com"):
            return ""
        path = (parsed.path or "").rstrip("/")
        if path.startswith("/search"):
            # Reddit's search UI appends its own tracking params (cId/iId/type/...)
            # alongside the real query - keep only `q`, don't drop the query
            # string wholesale like the subreddit/user branch below does, or
            # the search term itself (the only thing that matters) is lost.
            query_term = (parse_qs(parsed.query).get("q") or [""])[0].strip()
            return f"https://www.reddit.com/search?q={quote_plus(query_term)}" if query_term else ""
        return f"https://www.reddit.com{path}" if path else ""

    kind = (kind or "").strip().lower()
    if kind not in REDDIT_KINDS:
        kind = "subreddit"

    stripped = text.lstrip("/")
    lowered = stripped.lower()
    if lowered.startswith("r/"):
        sub = re.sub(r"[^A-Za-z0-9_]", "", stripped[2:])
        return f"https://www.reddit.com/r/{sub}" if sub else ""
    if lowered.startswith("u/"):
        handle = re.sub(r"[^A-Za-z0-9_-]", "", stripped[2:])
        return f"https://www.reddit.com/user/{handle}" if handle else ""
    if lowered.startswith("user/"):
        handle = re.sub(r"[^A-Za-z0-9_-]", "", stripped[5:])
        return f"https://www.reddit.com/user/{handle}" if handle else ""

    if kind == "user":
        handle = re.sub(r"[^A-Za-z0-9_-]", "", stripped)
        return f"https://www.reddit.com/user/{handle}" if handle else ""
    if kind == "search":
        return f"https://www.reddit.com/search?q={quote_plus(text)}"
    sub = re.sub(r"[^A-Za-z0-9_]", "", stripped)
    return f"https://www.reddit.com/r/{sub}" if sub else ""


def _derive_telegram_url(term):
    """Turn `https://t.me/channel`, `https://t.me/s/channel`, `@channel`, or
    a bare `channel` into the canonical `https://t.me/s/<channel>` preview
    URL the spider scrapes (see source_rss.py's telegram parser)."""
    text = (term or "").strip()
    if not text:
        return ""

    if re.match(r"^https?://", text, re.I):
        parsed = urlparse(text)
        host = parsed.netloc.lower().removeprefix("www.")
        if host not in {"t.me", "telegram.me"}:
            return ""
        parts = [p for p in parsed.path.split("/") if p]
        if not parts:
            return ""
        channel = parts[1] if parts[0].lower() == "s" and len(parts) > 1 else parts[0]
    else:
        channel = text.lstrip("@").strip()

    channel = re.sub(r"[^A-Za-z0-9_]", "", channel)
    return f"https://t.me/s/{channel}" if channel else ""


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


def _upsert_payload(source, default_limited=True):
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
    elif source_type_input == "reddit" and (url or name):
        # No `or url` fallback: an input that doesn't resolve to a real
        # reddit.com URL (wrong host, empty after stripping) must fail
        # create/update, not silently save whatever the user typed in as an
        # unusable "reddit" source - see create_source()/update_source()'s
        # `if not payload["url"]: return None`.
        reddit_kind = str(source.get("reddit_kind") or "").strip().lower()
        url = _derive_reddit_url(url or name, reddit_kind)
    elif source_type_input == "telegram" and (url or name):
        # Same reasoning as reddit above - e.g. a web.telegram.org/a/#<chat_id>
        # link (Telegram Web's internal numeric chat-ID deep link, not a
        # public @username/t.me link) must be rejected here, not saved as-is
        # only to silently scrape zero articles later.
        url = _derive_telegram_url(url or name)

    source_type = config._resolve_source_type(source_type_input, url)
    return {
        "url": url,
        "name": name or _default_name(url),
        "enabled": bool(source.get("enabled", True)),
        "source_type": source_type,
        "limited": bool(source.get("limited", default_limited)),
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

    existing = _fetch_source_by_id(source_id)
    default_limited = existing["limited"] if existing else False
    payload = _upsert_payload(source, default_limited=default_limited)
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
