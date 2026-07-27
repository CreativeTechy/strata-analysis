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
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# OPENAI_CHAT_BASE_URL/OPENAI_CHAT_MODEL are kept as the env var names for
# backward compatibility with existing deployments; they now point at the
# Responses API (see llm_client.py), not chat completions.
OPENAI_CHAT_BASE_URL = os.environ.get("OPENAI_CHAT_BASE_URL", "https://api.openai.com/v1/responses")
OPENAI_CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-5-nano")
EMBEDDING_MODEL = os.environ.get(
    "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
).strip()
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
# "cpu", "cuda"/"cuda:0", or "auto" (use CUDA if torch reports it available, else CPU).
SENTIMENT_CLASSIFIER_DEVICE = os.environ.get("SENTIMENT_CLASSIFIER_DEVICE", "cpu").strip()
SENTIMENT_CONFIDENCE_THRESHOLD = float(os.environ.get("SENTIMENT_CONFIDENCE_THRESHOLD", "0.55") or 0.55)


# --- Modular analysis pipeline (backend/analysis/) ---------------------------
# One model per stage, all configurable via env var, all lazy-loaded and
# reused across articles (see analysis/model_utils.py). Devices accept "cpu",
# "cuda"/"cuda:0", or "auto" (CUDA if available, else CPU).
#
# NOTE on migration pressure: changing EMBEDDING_MODEL (above) changes vector
# dimensionality (e.g. multilingual-e5-small is 384-dim,
# paraphrase-multilingual-mpnet-base-v2 is 768-dim). embeddings.cosine_similarity
# silently returns 0.0 when comparing vectors of different lengths, so existing
# rows embedded under an old model just stop matching anything - they are not
# flagged as stale. Re-embedding existing articles/projects after changing this
# is a manual follow-up (no automatic migration is run here).

# Zero-shot category + tone classification (MoritzLaurer/mDeBERTa-v3-base-mnli-xnli).
CLASSIFICATION_MODEL = os.environ.get(
    "CLASSIFICATION_MODEL", "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
).strip()
CLASSIFICATION_DEVICE = os.environ.get("CLASSIFICATION_DEVICE", "cpu").strip()
CLASSIFICATION_CONFIDENCE_THRESHOLD = float(
    os.environ.get("CLASSIFICATION_CONFIDENCE_THRESHOLD", "0.4") or 0.4
)

# Structured extraction (summary/feedback lists/opinions/ideas/key points) via
# a local instruction-tuned LLM, run through transformers text-generation.
STRUCTURED_EXTRACTION_MODEL = os.environ.get(
    "STRUCTURED_EXTRACTION_MODEL", "Qwen/Qwen2.5-7B-Instruct"
).strip()
STRUCTURED_EXTRACTION_DEVICE = os.environ.get("STRUCTURED_EXTRACTION_DEVICE", "cpu").strip()
STRUCTURED_EXTRACTION_MAX_NEW_TOKENS = int(
    os.environ.get("STRUCTURED_EXTRACTION_MAX_NEW_TOKENS", "900") or 900
)
STRUCTURED_EXTRACTION_TEMPERATURE = float(
    os.environ.get("STRUCTURED_EXTRACTION_TEMPERATURE", "0.0") or 0.0
)
# One retry with a correction prompt when the first pass isn't valid JSON /
# doesn't match the expected shape; 0 disables the retry.
STRUCTURED_EXTRACTION_MAX_RETRIES = int(
    os.environ.get("STRUCTURED_EXTRACTION_MAX_RETRIES", "1") or 1
)

# Optional dedicated NER model for entity extraction. Empty (default) means
# the stage is disabled and entities fall back to whatever structured
# extraction already produced (organizations/entities fields).
ENTITY_EXTRACTION_MODEL = os.environ.get("ENTITY_EXTRACTION_MODEL", "").strip()
ENTITY_EXTRACTION_DEVICE = os.environ.get("ENTITY_EXTRACTION_DEVICE", "cpu").strip()
ENTITY_EXTRACTION_CONFIDENCE_THRESHOLD = float(
    os.environ.get("ENTITY_EXTRACTION_CONFIDENCE_THRESHOLD", "0.5") or 0.5
)

# Chunking for long article text: applied uniformly by article_prep.py before
# handing text to any model with a limited context window.
ANALYSIS_CHUNK_SIZE_CHARS = int(os.environ.get("ANALYSIS_CHUNK_SIZE_CHARS", "2000") or 2000)
ANALYSIS_CHUNK_OVERLAP_CHARS = int(os.environ.get("ANALYSIS_CHUNK_OVERLAP_CHARS", "200") or 200)
# Hard cap on how much article text ever reaches a model, pre-chunking.
ANALYSIS_MAX_INPUT_CHARS = int(os.environ.get("ANALYSIS_MAX_INPUT_CHARS", "20000") or 20000)

# Source-language detection: metadata only (source_language/source_language_confidence
# on the articles table) - never used to translate or alter stored text, and
# every other stage's model is already multilingual-capable.
LANGUAGE_DETECTION_MODEL = os.environ.get(
    "LANGUAGE_DETECTION_MODEL", "papluca/xlm-roberta-base-language-detection"
).strip()
LANGUAGE_DETECTION_DEVICE = os.environ.get("LANGUAGE_DETECTION_DEVICE", "cpu").strip()
LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD = float(
    os.environ.get("LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD", "0.5") or 0.5
)


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
