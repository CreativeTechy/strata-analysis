"""Operator overrides for a small allowlist of tuning knobs that otherwise
only live in backend/.env - the Settings page (dashboard/src/components/
SettingsPage.jsx). Same override-over-default shape as
services/articles/source_trust.py: an override recorded in `runtime_settings`
wins, a missing row falls back to whatever config.py already computed from
`.env` at process start.

Deliberately a small, hand-picked allowlist (SETTINGS_SCHEMA below) rather
than every name in config.py - API keys and database credentials stay
.env-only and require a restart: there's no way to type in a new key here,
only to pick among providers whose credentials are already configured in
.env. Storage/import limits (record caps, upload size) are left out too, as
one-time-setup concerns rather than something worth adjusting live.

Because config.py's own values are plain module attributes computed once at
import (see config.py), an override takes effect immediately by writing
straight to `config.<KEY>` - the same thing the test suite already does via
`patch.object`/direct assignment. LLM_PROVIDER/COMPETITOR_ANALYSIS_LLM_PROVIDER
are the exception: each also fans out into provider-neutral LLM_*/
COMPETITOR_LLM_* attributes (credentials, base URL, model, request shape)
computed once at config.py import time, so switching the provider here goes
through config.apply_llm_provider_override() instead of a plain setattr - see
_apply() below. A provider with no credentials configured in .env behaves the
same as it always has (llm_client.py's "not configured" guard fires); this
does not invent an API key for a provider that was never given one.

SENTIMENT_CLASSIFIER_MODEL/_DEVICE are the other apparent exception: the
actual `transformers.pipeline` is memoized by sentiment_classifier.py's own
`@lru_cache(maxsize=1)` keyed on (model, device), so changing either here
doesn't hot-swap a loaded model in place - it just makes the next
classify_sentiment() call load (and cache) a different one, evicting the old.
The first call after a change pays that load cost.

ARTICLE_RELEVANCE_ACCEPT_THRESHOLD/_EXCLUDE_THRESHOLD keep the same "exclude
<= accept" invariant config.py enforces at import (see services/articles/
relevance_screening.py) - _cross_validate() below re-checks it against
whichever value is currently live (default or already-overridden), under
_CROSS_VALIDATION_LOCK, so two concurrent PATCH calls (one per threshold)
can never both read the pre-update values and leave the pair inverted.
"""
from __future__ import annotations

import threading

import config
import db

_LLM_PROVIDER_CHOICES = tuple(config._LLM_PROVIDER_DEFAULTS.keys())

# Held around _cross_validate()+_apply() for any key that _cross_validate()
# checks against another key's live value, so a concurrent PATCH to the
# paired key can't be applied in between this key's check and its own apply -
# which would otherwise let two individually-valid requests leave the pair
# inverted (see _cross_validate()).
_CROSS_VALIDATION_LOCK = threading.Lock()
_CROSS_VALIDATED_KEYS = frozenset({
    "ARTICLE_RELEVANCE_ACCEPT_THRESHOLD",
    "ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD",
})

SETTINGS_SCHEMA = {
    "LLM_PROVIDER": {
        "type": "enum",
        "choices": _LLM_PROVIDER_CHOICES,
        "description": (
            "Which backend every AI feature (article analysis, Intelligence Copilot, document splitting) talks to. "
            "Switching to a hosted provider sends uploaded document text to it, and only works if that provider's "
            "API key is already set in the server's .env."
        ),
    },
    "COMPETITOR_ANALYSIS_LLM_PROVIDER": {
        "type": "enum",
        "choices": _LLM_PROVIDER_CHOICES,
        "description": (
            "Overrides the provider for just competitor-study document splitting, competitor naming, and finding "
            "generation. Same off-machine caveat as LLM_PROVIDER above."
        ),
    },
    "ANALYSIS_CONCURRENCY": {
        "type": "int",
        "min": 1,
        "max": 32,
        "description": "How many articles one analysis run analyzes in parallel.",
    },
    "COMPETITOR_ANALYSIS_CONCURRENCY": {
        "type": "int",
        "min": 1,
        "max": 32,
        "description": "How many competitors' finding generation runs in parallel during one competitor analysis.",
    },
    "SENTIMENT_CLASSIFIER_PROVIDER": {
        "type": "enum",
        "choices": ("local", "hf_api"),
        "description": "Where the sentiment stage's model runs: in-process, or Hugging Face's hosted Inference API.",
    },
    "SENTIMENT_CLASSIFIER_MODEL": {
        "type": "string",
        "description": "Hugging Face model id the sentiment stage loads (only used when the provider above is \"local\").",
    },
    "SENTIMENT_CLASSIFIER_DEVICE": {
        "type": "string",
        "description": "Device the local sentiment model runs on: \"cpu\", \"cuda\"/\"cuda:0\", etc.",
    },
    "SENTIMENT_CONFIDENCE_THRESHOLD": {
        "type": "float",
        "min": 0.0,
        "max": 1.0,
        "description": "Minimum classifier confidence to trust a non-neutral sentiment label; below this, sentiment falls back to neutral.",
    },
    "CLASSIFICATION_PROVIDER": {
        "type": "enum",
        "choices": ("local", "hf_api"),
        "description": "Where the classification stage's model runs: in-process, or Hugging Face's hosted Inference API.",
    },
    "LLM_REQUEST_TIMEOUT_SECONDS": {
        "type": "int",
        "min": 5,
        "max": 600,
        "description": (
            "How long a single LLM call waits before giving up, for any call that doesn't set its own longer "
            "budget. Raise this before lowering concurrency if a slow/CPU-only local model legitimately needs longer."
        ),
    },
    "BUSINESS_PROFILE_LLM_TIMEOUT_SECONDS": {
        "type": "int",
        "min": 5,
        "max": 600,
        "description": "LLM timeout budget for deriving a competitor study's business profile.",
    },
    "COMPETITOR_FINDING_TIMEOUT_SECONDS": {
        "type": "int",
        "min": 5,
        "max": 600,
        "description": "LLM timeout budget for competitor finding generation - the heaviest competitor-analysis call.",
    },
    "ARTICLE_RELEVANCE_SCREENING_MODE": {
        "type": "enum",
        "choices": ("off", "observe", "enforce"),
        "description": (
            "\"off\" skips relevance screening entirely; \"observe\" records a score without excluding anything; "
            "\"enforce\" actually excludes articles scoring below the exclude threshold."
        ),
    },
    "ARTICLE_RELEVANCE_ACCEPT_THRESHOLD": {
        "type": "float",
        "min": -1.0,
        "max": 1.0,
        "description": (
            "Cosine-similarity score at or above which an article is confidently in-scope. Not a probability - "
            "tune it empirically. Must stay >= the exclude threshold below."
        ),
    },
    "ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD": {
        "type": "float",
        "min": -1.0,
        "max": 1.0,
        "description": (
            "Cosine-similarity score at or below which an article is excluded when the mode above is \"enforce\". "
            "Must stay <= the accept threshold above."
        ),
    },
    "EVIDENCE_CLAIM_SIMILARITY_THRESHOLD": {
        "type": "float",
        "min": -1.0,
        "max": 1.0,
        "description": (
            "Legacy compatibility knob: current Evidence rules don't use embedding similarity to merge assertions, "
            "so this has no effect unless an older ruleset reads it."
        ),
    },
}

# Captured once, at module import (before any override is ever applied), so
# resolve_all() can always show what ".env default" actually means even after
# an override has overwritten config's own attribute.
_ENV_DEFAULTS = {key: getattr(config, key) for key in SETTINGS_SCHEMA}


def _validate(key: str, raw_value) -> object:
    spec = SETTINGS_SCHEMA[key]
    if spec["type"] == "int":
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a whole number.")
        if value < spec["min"] or value > spec["max"]:
            raise ValueError(f"{key} must be between {spec['min']} and {spec['max']}.")
        return value
    if spec["type"] == "float":
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number.")
        if value < spec["min"] or value > spec["max"]:
            raise ValueError(f"{key} must be between {spec['min']} and {spec['max']}.")
        return value
    if spec["type"] == "enum":
        value = str(raw_value or "").strip().lower()
        if value not in spec["choices"]:
            raise ValueError(f"{key} must be one of: {', '.join(spec['choices'])}.")
        return value
    if spec["type"] == "string":
        value = str(raw_value or "").strip()
        if not value:
            raise ValueError(f"{key} is required.")
        return value
    raise ValueError(f"Unknown setting: {key!r}")


def _cross_validate(key: str, value) -> None:
    """A handful of keys constrain each other (see relevance_screening.py's
    own accept/exclude invariant) - checked against whatever is currently
    live so two separate PATCH calls can never leave them inverted."""
    if key == "ARTICLE_RELEVANCE_ACCEPT_THRESHOLD" and value < config.ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD:
        raise ValueError(
            f"ARTICLE_RELEVANCE_ACCEPT_THRESHOLD must be >= the exclude threshold "
            f"(currently {config.ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD})."
        )
    if key == "ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD" and value > config.ARTICLE_RELEVANCE_ACCEPT_THRESHOLD:
        raise ValueError(
            f"ARTICLE_RELEVANCE_EXCLUDE_THRESHOLD must be <= the accept threshold "
            f"(currently {config.ARTICLE_RELEVANCE_ACCEPT_THRESHOLD})."
        )


def _competitor_provider_pinned() -> bool:
    """True if COMPETITOR_ANALYSIS_LLM_PROVIDER has ever been explicitly set
    - in .env at process start, or via its own Settings override - as
    opposed to just inheriting LLM_PROVIDER. Checked against durable state
    (the env flag, and a fresh query of its own runtime_settings row) rather
    than an in-process flag, so it stays correct across load_overrides_on_
    startup()'s iteration order and doesn't need updating from every call
    site that might change it. Fails closed (pinned) on a DB error, so a
    flaky database can't make an LLM_PROVIDER change silently redirect
    competitor-study traffic to a provider nobody chose for it."""
    if config.COMPETITOR_ANALYSIS_LLM_PROVIDER_EXPLICIT:
        return True
    try:
        row = db.fetch_one(
            "select 1 from runtime_settings where key = %s",
            ("COMPETITOR_ANALYSIS_LLM_PROVIDER",),
        )
    except Exception:
        return True
    return row is not None


def _apply(key: str, value) -> None:
    """Push a resolved value everywhere it's actually read from, live."""
    if key == "LLM_PROVIDER":
        config.apply_llm_provider_override("app", value)
        # COMPETITOR_ANALYSIS_LLM_PROVIDER left unset inherits LLM_PROVIDER
        # (see config.py) - keep that inheritance live across a runtime
        # override too, unless the competitor scope has its own explicit
        # value, so switching providers here doesn't silently leave
        # competitor-study documents going to the provider that was active
        # at process start.
        if not _competitor_provider_pinned():
            config.apply_llm_provider_override("competitor", value)
    elif key == "COMPETITOR_ANALYSIS_LLM_PROVIDER":
        config.apply_llm_provider_override("competitor", value)
    else:
        setattr(config, key, value)


def load_overrides_on_startup() -> None:
    """Re-apply any persisted operator overrides on top of the .env defaults
    config.py already loaded - called once at backend startup, after
    migrations have run so the table is guaranteed to exist."""
    try:
        rows = db.fetch_all("select key, value from runtime_settings")
    except Exception:
        rows = []
    for row in rows or []:
        key = row.get("key")
        if key not in SETTINGS_SCHEMA:
            continue
        try:
            value = _validate(key, row.get("value"))
        except ValueError:
            continue
        _apply(key, value)


def resolve_all() -> dict[str, dict]:
    try:
        rows = db.fetch_all("select key, value, updated_at, set_by_name from runtime_settings")
    except Exception:
        rows = []
    overrides = {row["key"]: row for row in rows or [] if row.get("key")}

    result = {}
    for key, spec in SETTINGS_SCHEMA.items():
        override = overrides.get(key)
        # COMPETITOR_ANALYSIS_LLM_PROVIDER's ".env default" isn't a fixed
        # value when left unset - it tracks whatever LLM_PROVIDER currently
        # resolves to (see _apply() above), so the frozen _ENV_DEFAULTS
        # snapshot from import time would go stale the moment an operator
        # changes LLM_PROVIDER without ever touching this key directly.
        if key == "COMPETITOR_ANALYSIS_LLM_PROVIDER" and not config.COMPETITOR_ANALYSIS_LLM_PROVIDER_EXPLICIT:
            live_default = config.LLM_PROVIDER
        else:
            live_default = _ENV_DEFAULTS[key]
        entry = {
            "type": spec["type"],
            "description": spec["description"],
            "default": live_default,
        }
        if spec["type"] in ("int", "float"):
            entry["min"] = spec["min"]
            entry["max"] = spec["max"]
        elif spec["type"] == "enum":
            entry["choices"] = list(spec["choices"])
        if override:
            try:
                entry["value"] = _validate(key, override.get("value"))
            except ValueError:
                entry["value"] = live_default
            entry["is_default"] = False
            entry["updated_at"] = override.get("updated_at")
            entry["set_by"] = override.get("set_by_name")
        else:
            entry["value"] = live_default
            entry["is_default"] = True
            entry["updated_at"] = None
            entry["set_by"] = None
        result[key] = entry
    return result


def set_value(key: str, raw_value, user: dict) -> dict:
    if key not in SETTINGS_SCHEMA:
        raise ValueError(f"Unknown setting: {key!r}")
    if key in _CROSS_VALIDATED_KEYS:
        with _CROSS_VALIDATION_LOCK:
            return _set_value_unlocked(key, raw_value, user)
    return _set_value_unlocked(key, raw_value, user)


def _set_value_unlocked(key: str, raw_value, user: dict) -> dict:
    value = _validate(key, raw_value)
    _cross_validate(key, value)
    stored_value = str(value)
    set_by_name = (user or {}).get("username") or (user or {}).get("email")
    set_by_user_id = (user or {}).get("id")

    with db.transaction() as cur:
        cur.execute(
            """insert into runtime_settings_history (key, value, set_by_user_id, set_by_name)
               values (%s, %s, %s, %s)""",
            (key, stored_value, set_by_user_id, set_by_name),
        )
        cur.execute(
            """
            insert into runtime_settings (key, value, set_by_user_id, set_by_name)
            values (%s, %s, %s, %s)
            on conflict (key) do update set
                value = excluded.value,
                set_by_user_id = excluded.set_by_user_id,
                set_by_name = excluded.set_by_name,
                updated_at = now()
            returning key, value, set_by_name, updated_at
            """,
            (key, stored_value, set_by_user_id, set_by_name),
        )
        cur.fetchone()

    _apply(key, value)
    return resolve_all()[key]


def reset_value(key: str) -> dict:
    """Delete the override, reverting the key to its .env default."""
    if key not in SETTINGS_SCHEMA:
        raise ValueError(f"Unknown setting: {key!r}")
    if key in _CROSS_VALIDATED_KEYS:
        with _CROSS_VALIDATION_LOCK:
            return _reset_value_unlocked(key)
    return _reset_value_unlocked(key)


def _reset_value_unlocked(key: str) -> dict:
    # A reset re-check, same as set_value's: the .env default being reverted
    # to could itself invert the invariant against whatever the *other*
    # threshold is currently overridden to (e.g. the exclude threshold was
    # raised past this key's default before this key is reset) - surface
    # that instead of silently landing on an inverted pair.
    if key in _CROSS_VALIDATED_KEYS:
        _cross_validate(key, _ENV_DEFAULTS[key])
    with db.transaction() as cur:
        cur.execute("delete from runtime_settings where key = %s", (key,))
    if key == "COMPETITOR_ANALYSIS_LLM_PROVIDER" and not config.COMPETITOR_ANALYSIS_LLM_PROVIDER_EXPLICIT:
        # Un-pinning it should resume tracking the live LLM_PROVIDER, not
        # whatever it happened to inherit at process start.
        _apply(key, config.LLM_PROVIDER)
    else:
        _apply(key, _ENV_DEFAULTS[key])
    return resolve_all()[key]
