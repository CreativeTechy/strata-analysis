"""Central configuration for the generic source pipeline.

Single source of truth for the dynamic source list and for the credentials each
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

# --- LLM provider ------------------------------------------------------------
# `LLM_PROVIDER` picks which backend every AI feature (enrichment, Intelligence
# Copilot chat, project metadata suggestions, project/source discovery) talks
# to. Everything provider-specific - credentials, base URL, default model, and
# request/response shape - is resolved here and in llm_client.py; feature
# modules only ever call llm_client.chat_completion() and never branch on the
# provider themselves.
#
# OpenAI uses its Responses API; DeepSeek (and any other OpenAI-compatible
# provider) uses the chat-completions shape. Adding a new OpenAI-compatible
# provider only requires a new entry in _LLM_PROVIDER_DEFAULTS plus its two
# env vars below - no changes to llm_client.py's request logic.
_LLM_PROVIDER_DEFAULTS = {
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url_env": "OPENAI_CHAT_BASE_URL",
        "model_env": "OPENAI_CHAT_MODEL",
        "default_base_url": "https://api.openai.com/v1/responses",
        "default_model": "gpt-5-nano",
        "api_style": "responses",
    },
    "deepseek": {
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_CHAT_BASE_URL",
        "model_env": "DEEPSEEK_CHAT_MODEL",
        "default_base_url": "https://api.deepseek.com/v1/chat/completions",
        "default_model": "deepseek-chat",
        "api_style": "chat_completions",
    },
}

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai").strip().lower() or "openai"
if LLM_PROVIDER not in _LLM_PROVIDER_DEFAULTS:
    LLM_PROVIDER = "openai"

# Per-provider env vars are kept as top-level names (OPENAI_API_KEY et al. are
# unchanged from before this switch existed, so existing deployments that only
# ever set the OpenAI vars keep working with no changes). Only the active
# provider's values are used by llm_client.py, via LLM_API_KEY/LLM_CHAT_*
# below.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_CHAT_BASE_URL = os.environ.get(
    "OPENAI_CHAT_BASE_URL", _LLM_PROVIDER_DEFAULTS["openai"]["default_base_url"]
)
OPENAI_CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", _LLM_PROVIDER_DEFAULTS["openai"]["default_model"])

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_CHAT_BASE_URL = os.environ.get(
    "DEEPSEEK_CHAT_BASE_URL", _LLM_PROVIDER_DEFAULTS["deepseek"]["default_base_url"]
)
DEEPSEEK_CHAT_MODEL = os.environ.get("DEEPSEEK_CHAT_MODEL", _LLM_PROVIDER_DEFAULTS["deepseek"]["default_model"])

_LLM_PROVIDER_VALUES = {
    "openai": {
        "api_key": OPENAI_API_KEY,
        "base_url": OPENAI_CHAT_BASE_URL,
        "model": OPENAI_CHAT_MODEL,
    },
    "deepseek": {
        "api_key": DEEPSEEK_API_KEY,
        "base_url": DEEPSEEK_CHAT_BASE_URL,
        "model": DEEPSEEK_CHAT_MODEL,
    },
}

# Provider-neutral values llm_client.py (and, indirectly, every feature
# module) actually reads. Switching providers is a single env var
# (LLM_PROVIDER) away - nothing else needs to change.
_active_provider = _LLM_PROVIDER_DEFAULTS[LLM_PROVIDER]
_active_values = _LLM_PROVIDER_VALUES[LLM_PROVIDER]
LLM_API_KEY = _active_values["api_key"]
LLM_CHAT_BASE_URL = _active_values["base_url"]
LLM_CHAT_MODEL = _active_values["model"]
LLM_API_STYLE = _active_provider["api_style"]
LLM_API_KEY_ENV_NAME = _active_provider["api_key_env"]

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
EMBEDDING_DEVICE = os.environ.get("EMBEDDING_DEVICE", "cpu")

SCHEDULER_POLL_SECONDS = int(os.environ.get("SCHEDULER_POLL_SECONDS", "30") or 30)
SCHEDULER_STALE_RUN_MINUTES = int(os.environ.get("SCHEDULER_STALE_RUN_MINUTES", "180") or 180)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# Dedicated sentiment classifier (see sentiment_classifier.py) - the sole
# source of article `overall_sentiment`/`sentiment`. The LLM is never used
# for sentiment, so there is no toggle to fall back to it; if the classifier
# can't run, enrich.py defaults sentiment to "neutral" and logs it instead.
SENTIMENT_CLASSIFIER_MODEL = os.environ.get(
    "SENTIMENT_CLASSIFIER_MODEL", "cardiffnlp/twitter-roberta-base-sentiment-latest"
).strip()
# "cpu" or "cuda"/"cuda:0" etc.
SENTIMENT_CLASSIFIER_DEVICE = os.environ.get("SENTIMENT_CLASSIFIER_DEVICE", "cpu").strip()


# --- Auth -------------------------------------------------------------------
SESSION_COOKIE_NAME = os.environ.get("SESSION_COOKIE_NAME", "strata_session")
CSRF_COOKIE_NAME = os.environ.get("CSRF_COOKIE_NAME", "strata_csrf")
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "12") or 12)
# Cookies default to Secure (HTTPS-only). Set COOKIE_SECURE=false for plain-http
# local/dev deployments (e.g. this repo's docker-compose, which has no TLS
# termination configured) - the browser silently drops Secure cookies over http.
COOKIE_SECURE = _env_bool("COOKIE_SECURE", True)
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "lax").strip().lower()

# Comma-separated list of origins allowed to make credentialed cross-origin
# requests. The dashboard is normally served same-origin behind nginx/Vite's
# proxy, so this is mainly for local dev where the Vite dev server runs on a
# different port than uvicorn.
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

# Bootstrap admin, created on startup if the users table is empty.
ADMIN_BOOTSTRAP_USERNAME = os.environ.get("ADMIN_BOOTSTRAP_USERNAME", "").strip()
ADMIN_BOOTSTRAP_EMAIL = os.environ.get("ADMIN_BOOTSTRAP_EMAIL", "").strip()
ADMIN_BOOTSTRAP_PASSWORD = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "").strip()


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


KNOWN_SOURCE_TYPES = {"rss", "web", "social", "hashtag", "keyword", "username"}


def _resolve_source_type(source_type_input: str, url: str) -> str:
    """Pick the source_type to store, trusting an explicit known value.

    Legacy rows stored as rss/web whose URL is actually a social profile get
    upgraded to social, same as before this was centralized. hashtag/keyword/
    username are never overridden even though their derived URLs live on
    x.com/google.com (which would otherwise infer as social/web).
    """
    source_type_input = (source_type_input or "").strip().lower()
    inferred_type = _infer_source_type(url)
    if source_type_input in KNOWN_SOURCE_TYPES:
        if source_type_input in {"rss", "web"} and inferred_type == "social":
            return "social"
        return source_type_input
    return inferred_type or "rss"


def _normalize_source_record(row):
    url = (row.get("url") or "").strip()
    name = (row.get("name") or "").strip()
    source_type = _resolve_source_type(row.get("source_type") or "", url)
    return {
        "id": row.get("id"),
        "url": url,
        "name": name,
        "enabled": bool(row.get("enabled", True)),
        "source_type": source_type,
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
    env_sources = os.environ.get("SOURCES", "").strip()
    if env_sources:
        raw_urls = [u.strip() for u in env_sources.split(",") if u.strip()]
        return [
            _normalize_source_record(
                {
                    "url": url,
                    "name": urlparse(url).netloc or url,
                    "enabled": True,
                    "source_type": _infer_source_type(url),
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
            select id, url, name, enabled, source_type, created_at, updated_at
            from sources
            order by created_at asc
            """
        )
    except Exception:
        return []

    return [_normalize_source_record({**row, "source": "database"}) for row in records]
