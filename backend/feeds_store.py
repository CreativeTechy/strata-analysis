"""Supabase-backed feed management helpers.

The dashboard talks to the FastAPI backend, and the backend talks to Supabase
with the service key so feed management stays server-side.
"""

from urllib.parse import urlparse

import requests

import config


def _headers():
    return {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _feeds_endpoint():
    return f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/feeds"


def _response_error(resp):
    body = (resp.text or "").strip()
    if body:
        return f"HTTP {resp.status_code}: {body}"
    return f"HTTP {resp.status_code}"


def _normalize_record(row):
    url = (row.get("url") or "").strip()
    name = (row.get("name") or "").strip() or _default_name(url)
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
        "category": row.get("category") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "source": row.get("source", "supabase"),
    }


def _default_name(url):
    if not url:
        return "Feed"
    host = urlparse(url).netloc or url
    return host.removeprefix("www.")


def _fallback_records():
    return []


def list_feeds():
    """Return feed records from Supabase."""
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return _fallback_records()

    try:
        resp = requests.get(
            _feeds_endpoint(),
            headers=_headers(),
            params={
                "select": "id,url,name,enabled,source_type,category,created_at,updated_at",
                "order": "created_at.asc",
            },
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()
        if isinstance(rows, list) and rows:
            return [_normalize_record({**row, "source": "supabase"}) for row in rows]
    except Exception:
        pass

    return _fallback_records()


def _upsert_payload(feed):
    if isinstance(feed, str):
        feed = {"url": feed}
    elif not isinstance(feed, dict):
        feed = {}

    raw_url = feed.get("url") or feed.get("additionalProp1") or feed.get("value") or ""
    url = str(raw_url).strip()
    inferred_type = config._infer_source_type(url)
    source_type = (feed.get("source_type") or inferred_type or "rss").strip().lower() or "rss"
    if inferred_type == "social":
        source_type = "social"
    return {
        "url": url,
        "name": (feed.get("name") or "").strip() or _default_name(url),
        "enabled": bool(feed.get("enabled", True)),
        "source_type": source_type,
        "category": (feed.get("category") or "").strip(),
    }


def _fetch_feed_by_url(url):
    if not url or not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return None

    resp = requests.get(
        _feeds_endpoint(),
        headers=_headers(),
        params={
            "select": "id,url,name,enabled,source_type,category,created_at,updated_at",
            "url": f"eq.{url}",
            "limit": 1,
        },
        timeout=15,
    )
    resp.raise_for_status()
    rows = resp.json()
    if isinstance(rows, list) and rows:
        return _normalize_record({**rows[0], "source": "supabase"})
    return None


def _fetch_feed_by_id(feed_id):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return None

    resp = requests.get(
        _feeds_endpoint(),
        headers=_headers(),
        params={
            "select": "id,url,name,enabled,source_type,category,created_at,updated_at",
            "id": f"eq.{feed_id}",
            "limit": 1,
        },
        timeout=15,
    )
    resp.raise_for_status()
    rows = resp.json()
    if isinstance(rows, list) and rows:
        return _normalize_record({**rows[0], "source": "supabase"})
    return None


def bootstrap_feeds():
    """Return feed records for startup."""
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []

    try:
        resp = requests.get(
            _feeds_endpoint(),
            headers=_headers(),
            params={
                "select": "id,url,name,enabled,source_type,category,created_at,updated_at",
                "order": "created_at.asc",
            },
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()
        if isinstance(rows, list) and rows:
            return [_normalize_record({**row, "source": "supabase"}) for row in rows]
        return []
    except Exception:
        return []


def create_feed(feed):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return None

    payload = _upsert_payload(feed)
    if not payload["url"]:
        return None

    try:
        resp = requests.post(
            f"{_feeds_endpoint()}?on_conflict=url",
            headers={
                **_headers(),
                "Prefer": "resolution=merge-duplicates,return=representation",
            },
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json() if resp.content else None
        if isinstance(rows, list) and rows:
            return _normalize_record({**rows[0], "source": "supabase"})
        if isinstance(rows, dict) and rows:
            return _normalize_record({**rows, "source": "supabase"})
        return _fetch_feed_by_url(payload["url"])
    except Exception:
        return None

    return None


def update_feed(feed_id, feed):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return None

    payload = _upsert_payload(feed)

    try:
        resp = requests.patch(
            _feeds_endpoint(),
            headers={
                **_headers(),
                "Prefer": "return=representation",
            },
            params={"id": f"eq.{feed_id}"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json() if resp.content else None
        if isinstance(rows, list) and rows:
            return _normalize_record({**rows[0], "source": "supabase"})
        if isinstance(rows, dict) and rows:
            return _normalize_record({**rows, "source": "supabase"})
        return _fetch_feed_by_id(feed_id)
    except Exception:
        return None

    return None


def delete_feed(feed_id):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return False

    try:
        resp = requests.delete(
            _feeds_endpoint(),
            headers=_headers(),
            params={"id": f"eq.{feed_id}"},
            timeout=30,
        )
        resp.raise_for_status()
        return True
    except Exception:
        return False


def diagnose_feed_setup():
    """Return a short diagnostic string for feed CRUD failures."""
    if not config.SUPABASE_URL:
        return "SUPABASE_URL is missing."
    if not config.SUPABASE_SERVICE_KEY:
        return "SUPABASE_SERVICE_KEY is missing."

    try:
        resp = requests.get(
            _feeds_endpoint(),
            headers=_headers(),
            params={"select": "id", "limit": 1},
            timeout=15,
        )
        if not resp.ok:
            return f"Supabase request failed: {_response_error(resp)}"
        return ""
    except Exception as e:
        return f"Supabase request failed: {e}"
