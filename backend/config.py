"""Central configuration for the car-news pipeline.

Single source of truth for the dynamic feed list and for the credentials each
stage needs. Everything reads from here so swapping sources or rotating keys is
a one-place change.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
FEEDS_FILE = BASE_DIR / "feeds.txt"

# --- Credentials (env-driven; never hardcode secrets) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
# Writes must use the service_role key (bypasses RLS). Accept the legacy
# SUPABASE_KEY name as a fallback so existing CI secrets keep working.
SUPABASE_SERVICE_KEY = (
    os.environ.get("SUPABASE_SERVICE_KEY")
    or os.environ.get("SUPABASE_KEY", "")
)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")


def load_feeds():
    """Return the list of feed URLs.

    Priority: FEEDS env var (comma-separated) overrides feeds.txt. This keeps
    the scraper dynamic — change sources without touching spider code.
    """
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
