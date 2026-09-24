"""Locale-rendered view of one article's structured-extraction output fields.

The articles table (and its insight_json) stays in whatever language
analysis/structured_extraction.py produced it in - that canonical version is
what search, export, and cross-article comparison keep reading. A viewer
whose dashboard locale differs from it gets that same content rendered into
their locale on read, generated once via the configured LLM and cached in
`article_translations` rather than re-translated on every request - same
canonical-then-localized shape as services/intelligence/trend_summary.py.

This only ever touches the *output* fields an LLM originally generated
(summary, feedback lists, people opinions, frequent ideas) - never the
article's own uploaded text, and never sentiment/tone/category, which are
bounded enum labels a locale-aware UI translates for display on its own
(see dashboard/src/i18n), not something an LLM call should be spent re-
rendering.
"""

from __future__ import annotations

import json
import logging

import config
import db
from analysis.json_utils import JSONParseError, parse_json_response
from llm_client import chat_completion
from prompt_loader import load_prompt
from psycopg.types.json import Jsonb
from services.i18n.locales import language_instruction

logger = logging.getLogger(__name__)

TRANSLATION_SYSTEM_PROMPT = load_prompt("article_translation_system_prompt.txt")

TEXT_FIELDS = ("topic", "summary")
LIST_FIELDS = (
    "positive_feedback", "negative_feedback", "nice_to_have_features", "complaints",
    "great_features", "comfort_issues", "performance_feedback", "price_value_feedback",
    "maintenance_reliability_feedback", "technology_feedback", "safety_feedback",
)


def _database_ready() -> bool:
    return bool(config.DATABASE_URL)


def _build_payload(insight: dict) -> dict:
    payload = {field: str(insight.get(field) or "") for field in TEXT_FIELDS}
    for field in LIST_FIELDS:
        payload[field] = [str(v) for v in (insight.get(field) or [])]
    payload["people_opinions"] = [
        str((opinion or {}).get("opinion") or "") for opinion in (insight.get("people_opinions") or [])
    ]
    payload["frequent_ideas"] = [
        str((idea or {}).get("idea") or "") for idea in (insight.get("frequent_ideas") or [])
    ]
    return payload


def _has_translatable_content(insight: dict) -> bool:
    payload = _build_payload(insight)
    return any(payload[field].strip() for field in TEXT_FIELDS) or any(
        payload[field] for field in (*LIST_FIELDS, "people_opinions", "frequent_ideas")
    )


def _apply_translation(insight: dict, translated: dict) -> dict:
    """Merge a translated payload (same shape _build_payload produces) back
    onto `insight`. A field the model dropped, retyped, or returned with a
    mismatched array length is left at its original (untranslated) value
    rather than risk pairing translated text with the wrong list item."""
    result = dict(insight)

    for field in TEXT_FIELDS:
        value = translated.get(field)
        if isinstance(value, str) and value.strip():
            result[field] = value

    for field in LIST_FIELDS:
        values = translated.get(field)
        original = insight.get(field) or []
        if isinstance(values, list) and len(values) == len(original):
            result[field] = [str(v) for v in values]

    original_opinions = insight.get("people_opinions") or []
    translated_opinions = translated.get("people_opinions")
    if isinstance(translated_opinions, list) and len(translated_opinions) == len(original_opinions):
        result["people_opinions"] = [
            {**opinion, "opinion": str(translated_opinions[i])}
            for i, opinion in enumerate(original_opinions)
        ]

    original_ideas = insight.get("frequent_ideas") or []
    translated_ideas = translated.get("frequent_ideas")
    if isinstance(translated_ideas, list) and len(translated_ideas) == len(original_ideas):
        result["frequent_ideas"] = [
            {**idea, "idea": str(translated_ideas[i])} for i, idea in enumerate(original_ideas)
        ]

    return result


def _load_cached(article_id: int, locale: str) -> dict | None:
    if not _database_ready():
        return None
    return db.fetch_one(
        """
        select translated, source_analyzed_at
        from public.article_translations
        where article_id = %s and locale = %s
        """,
        (article_id, locale),
    )


def _save_cached(article_id: int, locale: str, translated: dict, source_analyzed_at) -> None:
    if not _database_ready():
        return
    db.execute(
        """
        insert into public.article_translations (article_id, locale, translated, source_analyzed_at, model)
        values (%s, %s, %s, %s, %s)
        on conflict (article_id, locale) do update
           set translated = excluded.translated,
               source_analyzed_at = excluded.source_analyzed_at,
               model = excluded.model,
               updated_at = now()
        """,
        (article_id, locale, Jsonb(translated), source_analyzed_at, config.LLM_CHAT_MODEL),
    )


def _translate_payload(insight: dict, locale: str) -> dict:
    payload = _build_payload(insight)
    raw = chat_completion(
        messages=[
            {"role": "system", "content": f"{TRANSLATION_SYSTEM_PROMPT}\n\n{language_instruction(locale)}"},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
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
    if not isinstance(parsed, dict):
        raise RuntimeError("translation response is not a JSON object")
    return parsed


def _build_result(analysis: dict, insight: dict, translated_payload: dict, locale: str, *, cached: bool) -> dict:
    merged_insight = _apply_translation(insight, translated_payload)
    result = {**analysis, "insight_json": merged_insight, "locale": locale, "cached": cached}
    summary = merged_insight.get("summary")
    if isinstance(summary, str) and summary.strip():
        result["summary"] = summary
    return result


def localize_article_analysis(analysis: dict, *, article_id: int, locale: str, force: bool = False) -> dict:
    """Return `analysis` (the shape `get_article_analysis()` returns) with its
    output fields rendered into `locale`.

    A no-op for the default locale - the canonical version already is that
    locale. Otherwise: a cached translation is reused as long as it was
    rendered from this article's current `analyzed_at` (a later reanalysis
    invalidates it); a cache miss or `force=True` spends one LLM call to
    translate every output field together, then caches it. If that call
    fails, the canonical (default-locale) analysis is returned instead of an
    error, tagged `locale_fallback: True` so the caller can say so - same
    fallback shape as generate_trend_summary().
    """
    locale = locale or config.DEFAULT_LOCALE
    if locale == config.DEFAULT_LOCALE:
        return analysis

    insight = analysis.get("insight_json") if isinstance(analysis.get("insight_json"), dict) else {}
    if not _has_translatable_content(insight):
        return {**analysis, "locale": locale}

    source_analyzed_at = analysis.get("analyzed_at")

    if not force:
        cached = _load_cached(article_id, locale)
        if cached is not None and (
            source_analyzed_at is None or cached.get("source_analyzed_at") == source_analyzed_at
        ):
            return _build_result(analysis, insight, cached["translated"], locale, cached=True)

    try:
        translated_payload = _translate_payload(insight, locale)
    except Exception:
        logger.exception("Article translation failed for article_id=%s locale=%s", article_id, locale)
        return {**analysis, "locale": config.DEFAULT_LOCALE, "locale_fallback": True}

    _save_cached(article_id, locale, translated_payload, source_analyzed_at)
    return _build_result(analysis, insight, translated_payload, locale, cached=False)
