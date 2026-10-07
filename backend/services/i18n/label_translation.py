"""Locale-rendered display labels for open-ended analysis values.

Most of what the dashboard shows either has a fixed vocabulary (sentiment,
tone, category, gender, age range - translated by the dashboard's own
catalogs) or is a canonical country (named by the browser's Intl data). What
is left is free text the model or a source document produced: life-situation
segments, regions that aren't a country ("Middle East", a city), and survey
metadata (question, population, cohort, answer). Those have no catalog to
look up, so they go through the configured LLM here, the same way
idea_translation.py renders "Top Ideas".

Cached by the label's own text per locale, shared across projects - see
migrations/0052_display_label_translations.sql. A label that fails to
translate comes back unchanged rather than failing the page.
"""

from __future__ import annotations

import json
import logging
import time

import config
import db
from analysis.json_utils import JSONParseError, parse_json_response
from llm_client import chat_completion
from prompt_loader import load_prompt
from services.i18n.locales import language_instruction

logger = logging.getLogger(__name__)

TRANSLATION_SYSTEM_PROMPT = load_prompt("label_translation_system_prompt.txt")

# Bounds on what one request may ask for, so this endpoint stays a label
# translator for what a dashboard view actually shows rather than a
# general-purpose text translation proxy onto the LLM.
MAX_LABELS_PER_REQUEST = 200
MAX_LABEL_LENGTH = 500
# Labels per LLM call - keeps each response short enough for a small local
# model to return the full array in order.
BATCH_SIZE = 40

# Same rationale as idea_translation.py's _failure_cache: an unreachable
# provider must not cost a fresh LLM_REQUEST_TIMEOUT_SECONDS wait on every
# page load for the same locale.
FAILURE_CACHE_SECONDS = 300
_failure_cache: dict[str, float] = {}


def _recent_failure(locale: str) -> bool:
    failed_at = _failure_cache.get(locale)
    if failed_at is None:
        return False
    return (time.monotonic() - failed_at) < FAILURE_CACHE_SECONDS


def _database_ready() -> bool:
    return bool(config.DATABASE_URL)


def _load_cached(locale: str, labels: list[str]) -> dict[str, str]:
    if not _database_ready() or not labels:
        return {}
    rows = db.fetch_all(
        """
        select source_text, translated_text
        from public.display_label_translations
        where locale = %s and source_text = any(%s)
        """,
        (locale, labels),
    )
    return {row["source_text"]: row["translated_text"] for row in rows}


def _save_cached(locale: str, translations: dict[str, str]) -> None:
    if not _database_ready() or not translations:
        return
    for source_text, translated_text in translations.items():
        db.execute(
            """
            insert into public.display_label_translations
                (locale, source_text, translated_text, model)
            values (%s, %s, %s, %s)
            on conflict (locale, source_text) do update
               set translated_text = excluded.translated_text,
                   model = excluded.model,
                   updated_at = now()
            """,
            (locale, source_text, translated_text, config.LLM_CHAT_MODEL),
        )


def _translate_batch(labels: list[str], locale: str) -> list[str]:
    raw = chat_completion(
        messages=[
            {"role": "system", "content": f"{TRANSLATION_SYSTEM_PROMPT}\n\n{language_instruction(locale)}"},
            {"role": "user", "content": json.dumps({"labels": labels}, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=2000,
        json_mode=True,
    )
    if raw is None:
        raise RuntimeError("translation model unavailable")
    try:
        parsed = parse_json_response(raw)
    except JSONParseError as exc:
        raise RuntimeError(f"invalid translation JSON: {exc}") from exc
    translated = (parsed or {}).get("labels") if isinstance(parsed, dict) else None
    if not isinstance(translated, list) or len(translated) != len(labels):
        raise RuntimeError("translation response has the wrong shape")
    return [str(value).strip() or source for value, source in zip(translated, labels)]


def clean_labels(values) -> list[str]:
    """Distinct, non-blank, length-bounded labels from a request body, in
    first-seen order, capped at MAX_LABELS_PER_REQUEST. Raises ValueError
    for a body that isn't a list of strings."""
    if not isinstance(values, list):
        raise ValueError("values must be a list of strings")
    seen: dict[str, None] = {}
    for value in values:
        if not isinstance(value, str):
            raise ValueError("values must be a list of strings")
        text = value.strip()
        if text and len(text) <= MAX_LABEL_LENGTH:
            seen.setdefault(text, None)
    return list(seen)[:MAX_LABELS_PER_REQUEST]


def translate_labels(labels: list[str], locale: str) -> dict[str, str]:
    """{label: translated label} for every label in `labels`.

    Identity for the default locale. Otherwise cached labels are reused and
    the rest translated in BATCH_SIZE chunks; a chunk that fails leaves its
    labels in their original text (and pauses further LLM attempts for this
    locale for FAILURE_CACHE_SECONDS) rather than failing the request.
    """
    locale = locale or config.DEFAULT_LOCALE
    if locale == config.DEFAULT_LOCALE or not labels:
        return {label: label for label in labels}

    translations = _load_cached(locale, labels)
    missing = [label for label in labels if label not in translations]
    for start in range(0, len(missing), BATCH_SIZE):
        if _recent_failure(locale):
            break
        batch = missing[start:start + BATCH_SIZE]
        try:
            translated = _translate_batch(batch, locale)
        except Exception:
            logger.exception("Label translation failed for locale=%s", locale)
            _failure_cache[locale] = time.monotonic()
            break
        _failure_cache.pop(locale, None)
        new_translations = dict(zip(batch, translated))
        _save_cached(locale, new_translations)
        translations.update(new_translations)

    return {label: translations.get(label, label) for label in labels}
