"""Central configuration for the generic source pipeline.

Single source of truth for the dynamic feed list and for the credentials each
stage needs. Everything reads from here so swapping sources or rotating keys is
a one-place change.
"""

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from trafilatura.feeds import find_feed_urls

import db

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


DATABASE_URL = db.get_database_url()
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_CHAT_BASE_URL = os.environ.get("DEEPSEEK_CHAT_BASE_URL", "https://api.deepseek.com/chat/completions")
DEEPSEEK_CHAT_MODEL = os.environ.get("DEEPSEEK_CHAT_MODEL", "deepseek-chat")
LOCAL_LLM_BASE_URL = os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
LOCAL_LLM_API_KEY = os.environ.get("LOCAL_LLM_API_KEY", "")
LOCAL_LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen2.5:14b-instruct")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
EMBEDDING_DEVICE = os.environ.get("EMBEDDING_DEVICE", "cpu")


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
        "source": row.get("source", "database"),
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

    if not DATABASE_URL:
        return []

    try:
        records = db.fetch_all(
            """
            select id, url, name, enabled, source_type, category, created_at, updated_at
            from feeds
            order by created_at asc
            """
        )
    except Exception:
        return []

    return [_normalize_source_record({**row, "source": "database"}) for row in records]
