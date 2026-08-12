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
        # "deepseek-chat"/"deepseek-reasoner" are DeepSeek's deprecated legacy
        # model aliases - this is the current supported model name.
        "default_model": "deepseek-v4-pro",
        "api_style": "chat_completions",
    },
    "ollama": {
        # Ollama serves an OpenAI-compatible chat-completions endpoint on
        # localhost and ignores the Authorization header entirely, so there
        # is no real key to set - OLLAMA_API_KEY exists only so LLM_API_KEY
        # is non-empty and llm_client's "not configured" guard doesn't fire.
        "api_key_env": "OLLAMA_API_KEY",
        "base_url_env": "OLLAMA_CHAT_BASE_URL",
        "model_env": "OLLAMA_CHAT_MODEL",
        "default_base_url": "http://localhost:11434/v1/chat/completions",
        "default_model": "llama3.1",
        "api_style": "chat_completions",
    },
}

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "deepseek").strip().lower() or "deepseek"
if LLM_PROVIDER not in _LLM_PROVIDER_DEFAULTS:
    LLM_PROVIDER = "deepseek"

# Per-provider env vars are kept as top-level names (OPENAI_API_KEY et al. are
# unchanged from before this switch existed, so existing deployments that only
# ever set the OpenAI vars keep working with no changes). Only the active
# provider's values are used by llm_client.py, via LLM_API_KEY/LLM_CHAT_*
# below.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# OPENAI_CHAT_BASE_URL/OPENAI_CHAT_MODEL are kept as the env var names for
# backward compatibility with existing deployments; they now point at the
# Responses API (see llm_client.py), not chat completions.
OPENAI_CHAT_BASE_URL = os.environ.get(
    "OPENAI_CHAT_BASE_URL", _LLM_PROVIDER_DEFAULTS["openai"]["default_base_url"]
)
OPENAI_CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", _LLM_PROVIDER_DEFAULTS["openai"]["default_model"])
# gpt-5-nano (the default OPENAI_CHAT_MODEL) is a reasoning model: the
# Responses API spends part of max_output_tokens on hidden reasoning tokens
# before writing any visible output. Left unset, OpenAI's default effort
# ("medium") can burn the *entire* budget on reasoning and return nothing
# visible even after llm_client.py's automatic retry-with-more-tokens - "low"
# leaves enough room for the actual JSON/text reply. One of minimal/low/medium/high.
OPENAI_REASONING_EFFORT = os.environ.get("OPENAI_REASONING_EFFORT", "low").strip().lower()

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_CHAT_BASE_URL = os.environ.get(
    "DEEPSEEK_CHAT_BASE_URL", _LLM_PROVIDER_DEFAULTS["deepseek"]["default_base_url"]
)
DEEPSEEK_CHAT_MODEL = os.environ.get("DEEPSEEK_CHAT_MODEL", _LLM_PROVIDER_DEFAULTS["deepseek"]["default_model"])

# See the "ollama" entry above re: this key being a placeholder, not a secret.
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "ollama")
OLLAMA_CHAT_BASE_URL = os.environ.get(
    "OLLAMA_CHAT_BASE_URL", _LLM_PROVIDER_DEFAULTS["ollama"]["default_base_url"]
)
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", _LLM_PROVIDER_DEFAULTS["ollama"]["default_model"])

_LLM_PROVIDER_VALUES = {
    "openai": {
        "api_key": OPENAI_API_KEY,
        "base_url": OPENAI_CHAT_BASE_URL,
        "model": OPENAI_CHAT_MODEL,
        "reasoning_effort": OPENAI_REASONING_EFFORT,
    },
    "deepseek": {
        "api_key": DEEPSEEK_API_KEY,
        "base_url": DEEPSEEK_CHAT_BASE_URL,
        "model": DEEPSEEK_CHAT_MODEL,
        "reasoning_effort": None,
    },
    "ollama": {
        "api_key": OLLAMA_API_KEY,
        "base_url": OLLAMA_CHAT_BASE_URL,
        "model": OLLAMA_CHAT_MODEL,
        "reasoning_effort": None,
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
LLM_REASONING_EFFORT = _active_values["reasoning_effort"]

# Competitor analysis (backend/services/competitors/ - document splitting,
# competitor naming, and finding generation) can run against a different
# provider than the rest of the app (enrichment, Intelligence Copilot,
# project/source discovery), e.g. Ollama for a fully offline setup, without
# switching everything else over. Left unset (the default), it just inherits
# LLM_PROVIDER above - nothing changes unless this is explicitly set.
COMPETITOR_ANALYSIS_LLM_PROVIDER = os.environ.get("COMPETITOR_ANALYSIS_LLM_PROVIDER", "").strip().lower()
if COMPETITOR_ANALYSIS_LLM_PROVIDER not in _LLM_PROVIDER_DEFAULTS:
    COMPETITOR_ANALYSIS_LLM_PROVIDER = LLM_PROVIDER

_competitor_provider = _LLM_PROVIDER_DEFAULTS[COMPETITOR_ANALYSIS_LLM_PROVIDER]
_competitor_values = _LLM_PROVIDER_VALUES[COMPETITOR_ANALYSIS_LLM_PROVIDER]
COMPETITOR_LLM_API_KEY = _competitor_values["api_key"]
COMPETITOR_LLM_CHAT_BASE_URL = _competitor_values["base_url"]
COMPETITOR_LLM_CHAT_MODEL = _competitor_values["model"]
COMPETITOR_LLM_API_STYLE = _competitor_provider["api_style"]
COMPETITOR_LLM_API_KEY_ENV_NAME = _competitor_provider["api_key_env"]
COMPETITOR_LLM_REASONING_EFFORT = _competitor_values["reasoning_effort"]

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


# --- Hugging Face Inference API (optional) -----------------------------------
HF_API_TOKEN = os.environ.get("HF_API_TOKEN", os.environ.get("HF_TOKEN", "")).strip()
# Leave unset (the default) to use HF's shared "hf-inference" provider
# routing - InferenceClient resolves the current host itself, so this repo
# doesn't hardcode a URL that HF can (and has) moved. Only set this to point
# at a dedicated HF Inference Endpoint's own URL instead.
HF_API_BASE_URL = os.environ.get("HF_API_BASE_URL", "").strip()
HF_API_TIMEOUT_SECONDS = float(os.environ.get("HF_API_TIMEOUT_SECONDS", "30") or 30)

# Dedicated sentiment classifier (see sentiment_classifier.py) - the sole
# source of article `overall_sentiment`/`sentiment`. The LLM is never used
# for sentiment, so there is no toggle to fall back to it; if the classifier
# can't run, enrich.py defaults sentiment to "neutral" and logs it instead.
SENTIMENT_CLASSIFIER_MODEL = os.environ.get(
    "SENTIMENT_CLASSIFIER_MODEL", "cardiffnlp/twitter-roberta-base-sentiment-latest"
).strip()
# "cpu", "cuda"/"cuda:0", or "auto" (use CUDA if torch reports it available, else CPU).
# Only relevant when SENTIMENT_CLASSIFIER_PROVIDER is "local".
SENTIMENT_CLASSIFIER_DEVICE = os.environ.get("SENTIMENT_CLASSIFIER_DEVICE", "cpu").strip()
SENTIMENT_CONFIDENCE_THRESHOLD = float(os.environ.get("SENTIMENT_CONFIDENCE_THRESHOLD", "0.55") or 0.55)
# "local" (default) or "hf_api" - see the Hugging Face Inference API section above.
SENTIMENT_CLASSIFIER_PROVIDER = os.environ.get("SENTIMENT_CLASSIFIER_PROVIDER", "local").strip().lower()


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
# Only relevant when CLASSIFICATION_PROVIDER is "local".
CLASSIFICATION_DEVICE = os.environ.get("CLASSIFICATION_DEVICE", "cpu").strip()
CLASSIFICATION_CONFIDENCE_THRESHOLD = float(
    os.environ.get("CLASSIFICATION_CONFIDENCE_THRESHOLD", "0.4") or 0.4
)
# "local" (default) or "hf_api" - see the Hugging Face Inference API section above.
CLASSIFICATION_PROVIDER = os.environ.get("CLASSIFICATION_PROVIDER", "local").strip().lower()

# Structured extraction (summary/feedback lists/opinions/ideas/key points) now
# goes through the configured LLM provider (llm_client.chat_completion), the
# same one used for enrichment/Copilot/discovery - no local model is loaded
# for this stage. STRUCTURED_EXTRACTION_MODEL/_DEVICE are no-op compatibility
# settings kept only so old .env files with these set don't break; they are
# not read by structured_extraction.py.
STRUCTURED_EXTRACTION_MODEL = os.environ.get("STRUCTURED_EXTRACTION_MODEL", "").strip()
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

# --- Scraping proxy: optional network egress ---------------------------------
# Any source can anti-bot-block requests from datacenter/cloud IP ranges (see
# scraper/spiders/source_rss.py's BLOCKED_STATUS_CODES/blocked-source
# reporting, and services/pipeline/pipeline.py's summary of it). Routing
# requests through a proxy is one mitigation for that. Unset (the default)
# changes nothing - requests go out directly. Full proxy URL, e.g.
# `http://user:pass@host:port` - Scrapy's HttpProxyMiddleware parses embedded
# basic-auth credentials from the URL itself, no separate credential fields
# needed.
# SCRAPE_PROXY_URL is the fallback used for every source type (rss/web/
# keyword/social/username/hashtag, and reddit/telegram when their own proxy
# below is unset). REDDIT_PROXY_URL/TELEGRAM_PROXY_URL override it for just
# those two platforms, e.g. to route them through a different proxy pool.
SCRAPE_PROXY_URL = os.environ.get("SCRAPE_PROXY_URL", "").strip()
REDDIT_PROXY_URL = os.environ.get("REDDIT_PROXY_URL", "").strip()
TELEGRAM_PROXY_URL = os.environ.get("TELEGRAM_PROXY_URL", "").strip()

# --- Reddit OAuth (optional) -------------------------------------------------
# Reddit's officially sanctioned path for programmatic access - an app-only
# ("client_credentials") token via a registered Reddit app - is far less
# likely to be blocked than the unauthenticated `.json` endpoints, at the
# cost of requiring credentials (which the rest of this source type
# deliberately doesn't). Both unset (the default) keeps using the public
# `.json` endpoints with no behavior change. Register an app (type "script")
# at https://www.reddit.com/prefs/apps to get a client id/secret.
REDDIT_OAUTH_CLIENT_ID = os.environ.get("REDDIT_OAUTH_CLIENT_ID", "").strip()
REDDIT_OAUTH_CLIENT_SECRET = os.environ.get("REDDIT_OAUTH_CLIENT_SECRET", "").strip()
# Reddit requires a distinctive User-Agent for API use (generic/browser UAs
# are rate-limited harder) - see https://github.com/reddit-archive/reddit/wiki/API#rules.
REDDIT_OAUTH_USER_AGENT = os.environ.get("REDDIT_OAUTH_USER_AGENT", "").strip()


def reddit_oauth_configured() -> bool:
    return bool(REDDIT_OAUTH_CLIENT_ID and REDDIT_OAUTH_CLIENT_SECRET)


# --- Google Custom Search (optional) -----------------------------------------
# General-web-search tier for "keyword" sources (see scraper/web_search.py and
# source_rss.py's start()) - a keyword otherwise only reaches Google News via
# its RSS feed, missing ordinary (non-news) web pages that mention it. Create
# a Programmable Search Engine at https://programmablesearchengine.google.com/
# (set it to search the whole web) for the engine id, and an API key with the
# Custom Search API enabled at https://console.cloud.google.com/apis/credentials.
# Free for 100 queries/day, then billed - unconfigured (the default) simply
# skips this tier and keyword sources behave exactly as before.
GOOGLE_CSE_API_KEY = os.environ.get("GOOGLE_CSE_API_KEY", "").strip()
GOOGLE_CSE_ENGINE_ID = os.environ.get("GOOGLE_CSE_ENGINE_ID", "").strip()


def google_cse_configured() -> bool:
    return bool(GOOGLE_CSE_API_KEY and GOOGLE_CSE_ENGINE_ID)


# --- GDELT (optional, on by default) -----------------------------------------
# Free, no-key news-search tier for "keyword" sources (see scraper/gdelt.py) -
# GDELT's own global news index, queried alongside (not instead of) the
# Google News RSS feed, so a keyword's news coverage doesn't depend solely on
# resolving Google's redirect-wrapper links. Set to false/0/no to disable.
GDELT_ENABLED = os.environ.get("GDELT_ENABLED", "true").strip().lower() not in {"false", "0", "no"}


# --- Skip re-enrichment for already-known articles ---------------------------
# When a scraped URL is already in the `articles` table with a successful
# analysis from the *current* enrichment version (analysis_pipeline_version ==
# PIPELINE_VERSION - see services/articles/enrich.py), reuse that stored
# analysis instead of paying for another LLM + embedding call. The article
# still flows through the normal save path either way, so a project seeing it
# for the first time still gets linked to it. Set false to force every scrape
# run to re-enrich everything (reanalyze.py's per-article endpoint is the
# other way to force a re-enrichment without this).
SKIP_EXISTING_ARTICLES = _env_bool("SKIP_EXISTING_ARTICLES", True)


# --- Streaming enrichment concurrency ----------------------------------------
# How many articles StreamingEnrichPipeline (scraper/pipelines.py) enriches in
# parallel, off Scrapy's reactor thread, instead of one at a time blocking the
# whole crawl. Kept deliberately low by default rather than tuned to any one
# provider's ceiling, since LLM_PROVIDER is user-selectable and the limiting
# factor differs a lot by provider:
#   - deepseek: no published per-minute limit, but a shared *concurrency* cap
#     (500-2500 in-flight requests) at the account level, across everything
#     else that account is doing too - not just this app.
#   - openai: tier-based (by cumulative spend); a fresh/low-spend account's
#     Tier 1 default is generously above this default for a small/cheap model,
#     but nowhere near unlimited.
#   - ollama: no external rate limit at all, but real local hardware/VRAM
#     throughput instead - a low default avoids swamping a single local
#     model server (and the local embedding model, which competes for the
#     same CPU/GPU) with too many simultaneous generations.
# Raise this if you have a well-provisioned account/host and have confirmed
# your own provider's actual limits comfortably clear it.
try:
    ENRICH_CONCURRENCY = max(1, int(os.environ.get("ENRICH_CONCURRENCY", "4")))
except ValueError:
    ENRICH_CONCURRENCY = 4


# --- Google News link-decode concurrency -------------------------------------
# How many news.google.com/rss/articles/... redirect-wrapper links
# source_rss.py's parse_feed() decodes at once (see googlenewsdecoder in
# CLAUDE.md). A Google News search feed carries up to ~100 of these, each
# decode being a real network round trip (fetch the wrapper page, then a
# signed batchexecute call) - resolved one at a time this was measured at
# 7-11 minutes for a single feed, blocking the whole crawl for that entire
# span. Higher than ENRICH_CONCURRENCY by default: this endpoint's own
# rate-limiting is undocumented (unlike the LLM providers ENRICH_CONCURRENCY
# is sized against), so this is a starting point to tune from, not a
# researched ceiling - lower it if you see a rise in decode failures
# (skipped links, not errors - see _resolve_google_news_link).
try:
    GOOGLE_NEWS_DECODE_CONCURRENCY = max(1, int(os.environ.get("GOOGLE_NEWS_DECODE_CONCURRENCY", "8")))
except ValueError:
    GOOGLE_NEWS_DECODE_CONCURRENCY = 8


# Apply pending schema migrations when the API starts. Set false to manage them
# out of band (`python migrate.py`) — e.g. when several backend replicas share
# one database and only a deploy step should migrate it.
MIGRATE_ON_STARTUP = _env_bool("MIGRATE_ON_STARTUP", True)


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
            "threads.net",
        )
    )


def _looks_like_reddit_url(url: str) -> bool:
    host = urlparse((url or "").strip()).netloc.lower().removeprefix("www.")
    return host == "reddit.com" or host.endswith(".reddit.com")


def _looks_like_telegram_url(url: str) -> bool:
    host = urlparse((url or "").strip()).netloc.lower().removeprefix("www.")
    return host in {"t.me", "telegram.me"}


def _infer_source_type(url: str) -> str:
    if _looks_like_feed_url(url):
        return "rss"
    if _looks_like_reddit_url(url):
        return "reddit"
    if _looks_like_telegram_url(url):
        return "telegram"
    if _looks_like_social_url(url):
        return "social"
    return "web"


KNOWN_SOURCE_TYPES = {"rss", "web", "social", "hashtag", "keyword", "username", "reddit", "telegram"}


def _resolve_source_type(source_type_input: str, url: str) -> str:
    """Pick the source_type to store, trusting an explicit known value.

    Legacy rows stored as rss/web whose URL is actually a social profile get
    upgraded to social, same as before this was centralized. reddit.com used
    to be lumped into the generic social bucket, so a legacy row stored as
    social (or rss/web) whose URL is actually reddit.com/t.me gets upgraded
    to the dedicated reddit/telegram type the same way. hashtag/keyword/
    username are never overridden even though their derived URLs live on
    x.com/google.com (which would otherwise infer as social/web).
    """
    source_type_input = (source_type_input or "").strip().lower()
    inferred_type = _infer_source_type(url)
    if source_type_input in KNOWN_SOURCE_TYPES:
        if source_type_input in {"rss", "web", "social"} and inferred_type in {"reddit", "telegram"}:
            return inferred_type
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
    """Return configured source records with source_type preserved.

    Scoped to the project's assigned sources when PIPELINE_PROJECT_ID is set
    (the scraper subprocess always has this when a project was selected -
    see run_scraper_pipeline), otherwise every source in the table.
    """
    if not DATABASE_URL:
        return []

    project_id = os.environ.get("PIPELINE_PROJECT_ID", "").strip()
    try:
        if project_id:
            records = db.fetch_all(
                """
                select s.id, s.url, s.name, s.enabled, s.source_type, s.created_at, s.updated_at
                from sources s
                inner join project_sources ps on ps.source_id = s.id
                where ps.project_id = %s
                order by s.created_at asc
                """,
                (int(project_id),),
            )
        else:
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
