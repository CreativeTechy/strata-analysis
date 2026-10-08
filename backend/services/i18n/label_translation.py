"""Locale-rendered display labels for open-ended analysis values.

Most of what the dashboard shows either has a fixed vocabulary (sentiment,
tone, category, gender, age range - translated by the dashboard's own
catalogs) or is a canonical country (named by the browser's Intl data). What
is left is free text the model or a source document produced: life-situation
segments, regions that aren't a country ("Middle East", a city), and survey
metadata (question, population, cohort, answer). Those have no catalog to
look up, so they go through the configured LLM here, the same way
idea_translation.py renders "Top Ideas".

Cached per (project, locale, label text) - see
migrations/0054_display_label_translations.sql. The text comes out of a
project's own documents, so it is never shared across projects. A label that
fails to translate comes back unchanged rather than failing the page.
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
from services.articles.analysis_defaults import FATAL_ANALYSIS_ERRORS
from services.i18n.locales import language_instruction

logger = logging.getLogger(__name__)

TRANSLATION_SYSTEM_PROMPT = load_prompt("label_translation_system_prompt.txt")

# Bounds on what one request may ask for, so this endpoint stays a label
# translator for what a dashboard view actually shows rather than a
# general-purpose text translation proxy onto the LLM.
MAX_LABELS_PER_REQUEST = 200
MAX_LABEL_LENGTH = 500
# A batch is capped by label count and by total characters, so the response
# (sized from the batch, see _output_budget) always fits the model's output
# and is short enough for a small local model to return in order.
BATCH_SIZE = 40
MAX_BATCH_CHARS = 2000

# Same rationale as idea_translation.py's _failure_cache: an unreachable
# provider must not cost a fresh LLM_REQUEST_TIMEOUT_SECONDS wait on every
# page load. Keyed per (project, locale) and only armed by a provider-level
# failure (FATAL_ANALYSIS_ERRORS), never by one batch the model mangled.
FAILURE_CACHE_SECONDS = 300
_failure_cache: dict[tuple[int, str], float] = {}


def _recent_failure(project_id: int, locale: str) -> bool:
    failed_at = _failure_cache.get((project_id, locale))
    if failed_at is None:
        return False
    return (time.monotonic() - failed_at) < FAILURE_CACHE_SECONDS


def _database_ready() -> bool:
    return bool(config.DATABASE_URL)


def _load_cached(project_id: int, locale: str, labels: list[str]) -> dict[str, str]:
    if not _database_ready() or not labels:
        return {}
    rows = db.fetch_all(
        """
        select source_text, translated_text
        from public.display_label_translations
        where project_id = %s and locale = %s and source_text = any(%s)
        """,
        (project_id, locale, labels),
    )
    return {row["source_text"]: row["translated_text"] for row in rows}


def _save_cached(project_id: int, locale: str, translations: dict[str, str]) -> None:
    if not _database_ready() or not translations:
        return
    for source_text, translated_text in translations.items():
        db.execute(
            """
            insert into public.display_label_translations
                (project_id, locale, source_text, translated_text, model)
            values (%s, %s, %s, %s, %s)
            on conflict (project_id, locale, source_text) do update
               set translated_text = excluded.translated_text,
                   model = excluded.model,
                   updated_at = now()
            """,
            (project_id, locale, source_text, translated_text, config.LLM_CHAT_MODEL),
        )


def _output_budget(labels: list[str]) -> int:
    # Worst case is roughly a token per source character once translated
    # (Arabic tokenizes poorly), plus the JSON scaffolding around each item.
    return 256 + sum(2 * len(label) + 16 for label in labels)


def _translate_batch(labels: list[str], locale: str) -> list[str]:
    raw = chat_completion(
        messages=[
            {"role": "system", "content": f"{TRANSLATION_SYSTEM_PROMPT}\n\n{language_instruction(locale)}"},
            {"role": "user", "content": json.dumps({"labels": labels}, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=_output_budget(labels),
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


def _translate_resilient(labels: list[str], locale: str) -> dict[str, str]:
    """Translate what can be translated: a batch the model mangled (cut off,
    wrong-length array) is split in half and retried, down to a single label,
    so one bad label costs only itself. Provider-level failures propagate."""
    try:
        return dict(zip(labels, _translate_batch(labels, locale)))
    except FATAL_ANALYSIS_ERRORS:
        raise
    except Exception:
        if len(labels) == 1:
            logger.warning("Label translation failed for locale=%s, keeping source text", locale, exc_info=True)
            return {}
        logger.info("Label batch of %d failed for locale=%s, retrying in halves", len(labels), locale)
        mid = len(labels) // 2
        return {**_translate_resilient(labels[:mid], locale), **_translate_resilient(labels[mid:], locale)}


def _batches(labels: list[str]):
    batch: list[str] = []
    chars = 0
    for label in labels:
        if batch and (len(batch) >= BATCH_SIZE or chars + len(label) > MAX_BATCH_CHARS):
            yield batch
            batch, chars = [], 0
        batch.append(label)
        chars += len(label)
    if batch:
        yield batch


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


def translate_labels(project_id: int, labels: list[str], locale: str) -> dict[str, str]:
    """{label: translated label} for every label in `labels`, rendered for
    `project_id` (whose documents the labels came from).

    Identity for the default locale. Otherwise cached labels are reused and
    the rest translated in batches; a label the model can't translate keeps
    its original text. Only a provider-level failure (unreachable, auth,
    quota) stops the remaining batches and pauses further LLM attempts for
    this project and locale for FAILURE_CACHE_SECONDS.
    """
    locale = locale or config.DEFAULT_LOCALE
    if locale == config.DEFAULT_LOCALE or not labels:
        return {label: label for label in labels}

    translations = _load_cached(project_id, locale, labels)
    missing = [label for label in labels if label not in translations]
    for batch in _batches(missing):
        if _recent_failure(project_id, locale):
            break
        try:
            new_translations = _translate_resilient(batch, locale)
        except FATAL_ANALYSIS_ERRORS:
            logger.exception("Label translation provider failed for project=%s locale=%s", project_id, locale)
            _failure_cache[(project_id, locale)] = time.monotonic()
            break
        _failure_cache.pop((project_id, locale), None)
        if new_translations:
            _save_cached(project_id, locale, new_translations)
        translations.update(new_translations)

    return {label: translations.get(label, label) for label in labels}
