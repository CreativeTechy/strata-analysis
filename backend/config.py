"""Central configuration for the car-news pipeline.

Single source of truth for the dynamic feed list and for the credentials each
stage needs. Everything reads from here so swapping sources or rotating keys is
a one-place change.
"""

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import requests
from trafilatura.feeds import find_feed_urls

BASE_DIR = Path(__file__).resolve().parent
DOTENV_FILE = BASE_DIR / ".env"

def _load_dotenv():
    """Load simple KEY=VALUE pairs from backend/.env if present."""
    if not DOTENV_FILE.exists():
        return

    try:
        for raw_line in DOTENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        # If dotenv parsing fails, keep going with the already-loaded env.
        pass


_load_dotenv()


# --- Credentials (env-driven; never hardcode secrets) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
# Writes must use the service_role key (bypasses RLS). Accept the legacy
# SUPABASE_KEY name as a fallback so existing CI secrets keep working.
SUPABASE_SERVICE_KEY = (
    os.environ.get("SUPABASE_SERVICE_KEY")
    or os.environ.get("SUPABASE_KEY", "")
)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


def _looks_like_feed_url(url: str) -> bool:
    url = (url or "").strip().lower()
    return any(
        token in url
        for token in (
            "/feed",
            "/rss",
            "/atom",
            ".xml",
            ".rss",
            ".rdf",
            "?feed=",
        )
    )


def _looks_like_social_url(url: str) -> bool:
    host = urlparse((url or "").strip()).netloc.lower()
    return any(
        domain in host
        for domain in (
            "x.com",
            "twitter.com",
            "facebook.com",
            "instagram.com",
            "tiktok.com",
            "linkedin.com",
            "youtube.com",
            "reddit.com",
            "threads.net",
        )
    )


def _infer_source_type(url: str) -> str:
    if _looks_like_feed_url(url):
        return "rss"
    if _looks_like_social_url(url):
        return "social"
    return "web"


def _normalize_source_record(row):
    url = (row.get("url") or "").strip()
    name = (row.get("name") or "").strip()
    inferred_type = _infer_source_type(url)
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
        "source": row.get("source", "supabase"),
    }


@lru_cache(maxsize=256)
def _discover_feed_urls(url: str):
    """Return discovered feed URLs for a homepage, or [] if none are found."""
    if not url:
        return []
    try:
        discovered = find_feed_urls(url)
        if isinstance(discovered, list):
            return [u.strip() for u in discovered if u and u.strip()]
    except Exception:
        pass
    return []


def _load_feed_records_from_supabase():
    """Return Supabase feed rows, or None if Supabase is unavailable."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return None

    try:
        resp = requests.get(
            f"{SUPABASE_URL.rstrip('/')}/rest/v1/feeds",
            headers={
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                "Accept": "application/json",
            },
            params={
                "select": "id,url,name,enabled,source_type,category,created_at,updated_at",
                "order": "created_at.asc",
            },
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()
        return rows if isinstance(rows, list) else []
    except Exception:
        return None


def load_feed_records():
    """Return feed records from Supabase, or an empty list if unavailable."""
    rows = _load_feed_records_from_supabase()
    if rows is None:
        return []
    return [_normalize_source_record(row) for row in rows]


def load_source_records():
    """Return configured source records with source_type preserved."""
    env_feeds = os.environ.get("FEEDS", "").strip()
    if env_feeds:
        raw_urls = [u.strip() for u in env_feeds.split(",") if u.strip()]
        return [
            _normalize_source_record(
                {
                    "url": url,
                    "name": urlparse(url).netloc or url,
                    "enabled": True,
                    "source_type": _infer_source_type(url),
                    "category": "",
                    "source": "env",
                }
            )
            for url in raw_urls
        ]

    records = _load_feed_records_from_supabase()
    if records is None:
        return []
    return [_normalize_source_record(row) for row in records]


def load_feeds():
    """Return the active feed URLs for the scraper.

    Priority:
    1. FEEDS env var override
    2. Supabase feeds table
    """
    normalized = []
    seen = set()
    for record in load_source_records():
        if not record.get("enabled", True):
            continue
        url = (record.get("url") or "").strip()
        source_type = (record.get("source_type") or "rss").strip().lower()
        if not url:
            continue

        candidate_urls = [url]
        if source_type == "rss" and not _looks_like_feed_url(url):
            candidate_urls = _discover_feed_urls(url) or [url]

        for candidate in candidate_urls:
            candidate = (candidate or "").strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                normalized.append(candidate)

    return normalized
