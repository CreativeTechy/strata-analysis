"""Central configuration for the car-news pipeline.

Single source of truth for the dynamic feed list and for the credentials each
stage needs. Everything reads from here so swapping sources or rotating keys is
a one-place change.
"""

import os
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
FEEDS_FILE = BASE_DIR / "feeds.txt"
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


def load_fallback_feed_urls():
    """Return feed URLs from env/file when Supabase is unavailable."""
    env_feeds = os.environ.get("FEEDS", "").strip()
    if env_feeds:
        return [u.strip() for u in env_feeds.split(",") if u.strip()]

    if not FEEDS_FILE.exists():
        return []

    feeds = []
    for line in FEEDS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            feeds.append(line)
    return feeds


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
    3. feeds.txt fallback
    """
    env_feeds = os.environ.get("FEEDS", "").strip()
    if env_feeds:
        return [u.strip() for u in env_feeds.split(",") if u.strip()]

    records = _load_feed_records_from_supabase()
    if records is not None:
        enabled_urls = [
            r.get("url", "").strip()
            for r in records
            if r.get("enabled", True) and r.get("url")
        ]
        if enabled_urls:
            return enabled_urls
        if records:
            return []

    return load_fallback_feed_urls()
