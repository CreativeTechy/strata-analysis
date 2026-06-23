"""Central configuration for the car-news pipeline.

Single source of truth for the dynamic feed list and for the credentials each
stage needs. Everything reads from here so swapping sources or rotating keys is
a one-place change.
"""

import os
from functools import lru_cache
from pathlib import Path

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
    return rows


def load_feeds():
    """Return the active feed URLs for the scraper.

    Priority:
    1. FEEDS env var override
    2. Supabase feeds table
    """
    env_feeds = os.environ.get("FEEDS", "").strip()
    if env_feeds:
        raw_urls = [u.strip() for u in env_feeds.split(",") if u.strip()]
    else:
        records = _load_feed_records_from_supabase()
        if records is not None:
            raw_urls = [
                r.get("url", "").strip()
                for r in records
                if r.get("enabled", True) and r.get("url")
            ]
        else:
            raw_urls = []

    normalized = []
    seen = set()
    for url in raw_urls:
        candidate_urls = [url] if _looks_like_feed_url(url) else _discover_feed_urls(url)
        if not candidate_urls:
            candidate_urls = [url]

        for candidate in candidate_urls:
            candidate = (candidate or "").strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                normalized.append(candidate)

    return normalized
