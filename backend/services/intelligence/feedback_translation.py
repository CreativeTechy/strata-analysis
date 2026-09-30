"""Locale-rendered strings for the Reports page's "Categorized feedback"
section (insights.positive_feedback/negative_feedback inside
get_project_intelligence()'s response).

Same reasoning and cache shape as idea_translation.py: positive_feedback/
negative_feedback are recomputed from scratch on every request for whatever
(project_id, period, run_id) scope was asked for, so this caches by the
feedback item's own text (per project + locale) rather than by request scope.
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

# Same prompt idea_translation.py uses - it already covers standalone
# idea/complaint/praise/suggestion phrases in general, which is exactly the
# shape of a positive_feedback/negative_feedback item's `text`.
TRANSLATION_SYSTEM_PROMPT = load_prompt("idea_translation_system_prompt.txt")

FAILURE_CACHE_SECONDS = 300
_failure_cache: dict[tuple[int, str], float] = {}

_FEEDBACK_KEYS = ("positive_feedback", "negative_feedback")


def _recent_failure(project_id: int, locale: str) -> bool:
    failed_at = _failure_cache.get((project_id, locale))
    if failed_at is None:
        return False
    return (time.monotonic() - failed_at) < FAILURE_CACHE_SECONDS


def _record_failure(project_id: int, locale: str) -> None:
    _failure_cache[(project_id, locale)] = time.monotonic()


def _clear_failure(project_id: int, locale: str) -> None:
    _failure_cache.pop((project_id, locale), None)


def _database_ready() -> bool:
    return bool(config.DATABASE_URL)


def _load_cached(project_id: int, locale: str, texts: list[str]) -> dict[str, str]:
    if not _database_ready() or not texts:
        return {}
    rows = db.fetch_all(
        """
        select source_text, translated_text
        from public.project_feedback_translations
        where project_id = %s and locale = %s and source_text = any(%s)
        """,
        (project_id, locale, texts),
    )
    return {row["source_text"]: row["translated_text"] for row in rows}


def _save_cached(project_id: int, locale: str, translations: dict[str, str]) -> None:
    if not _database_ready() or not translations:
        return
    for source_text, translated_text in translations.items():
        db.execute(
            """
            insert into public.project_feedback_translations
                (project_id, locale, source_text, translated_text, model)
            values (%s, %s, %s, %s, %s)
            on conflict (project_id, locale, source_text) do update
               set translated_text = excluded.translated_text,
                   model = excluded.model,
                   updated_at = now()
            """,
            (project_id, locale, source_text, translated_text, config.LLM_CHAT_MODEL),
        )


def _translate_texts(texts: list[str], locale: str) -> list[str]:
    raw = chat_completion(
        messages=[
            {"role": "system", "content": f"{TRANSLATION_SYSTEM_PROMPT}\n\n{language_instruction(locale)}"},
            {"role": "user", "content": json.dumps({"ideas": texts}, ensure_ascii=False)},
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
    translated = (parsed or {}).get("ideas") if isinstance(parsed, dict) else None
    if not isinstance(translated, list) or len(translated) != len(texts):
        raise RuntimeError("translation response has the wrong shape")
    return [str(v) for v in translated]


def localize_categorized_feedback(intelligence: dict, *, project_id: int, locale: str) -> dict:
    """Return `intelligence` with insights.positive_feedback/negative_feedback's
    `text` rendered into `locale`.

    A no-op for the default locale or when both lists are empty. Otherwise:
    items already cached for this project+locale are reused as-is; the
    remaining ones are translated together in one LLM call and cached by
    their own text, not by (project_id, period, run_id) - see module
    docstring. A text that fails to translate (a down provider, or the model
    dropping it) is left in its original English rather than blanked out or
    failing the whole dashboard load.
    """
    locale = locale or config.DEFAULT_LOCALE
    insights = intelligence.get("insights") if isinstance(intelligence.get("insights"), dict) else None
    if locale == config.DEFAULT_LOCALE or not insights:
        return intelligence

    feedback_lists = {key: insights.get(key) for key in _FEEDBACK_KEYS if isinstance(insights.get(key), list)}
    if not feedback_lists:
        return intelligence

    distinct_texts = sorted({
        str(item.get("text") or "").strip()
        for items in feedback_lists.values()
        for item in items
        if item.get("text")
    })
    if not distinct_texts:
        return intelligence

    # A cache read/write failure (e.g. a database that hasn't been migrated
    # yet) must degrade to "no cached translations" / "translation not
    # persisted" rather than 500 the whole /intelligence request - unlike a
    # failed LLM call, that isn't worth a 5-minute failure short-circuit
    # since it isn't tied to the provider being reachable.
    try:
        translations = _load_cached(project_id, locale, distinct_texts)
    except Exception:
        logger.exception("Feedback translation cache read failed for project_id=%s locale=%s", project_id, locale)
        translations = {}
    missing = [text for text in distinct_texts if text not in translations]

    if missing and not _recent_failure(project_id, locale):
        try:
            translated = _translate_texts(missing, locale)
        except Exception:
            logger.exception("Feedback translation failed for project_id=%s locale=%s", project_id, locale)
            _record_failure(project_id, locale)
        else:
            _clear_failure(project_id, locale)
            new_translations = dict(zip(missing, translated))
            try:
                _save_cached(project_id, locale, new_translations)
            except Exception:
                logger.exception("Feedback translation cache write failed for project_id=%s locale=%s", project_id, locale)
            translations.update(new_translations)

    localized_lists = {
        key: [{**item, "text": translations.get(str(item.get("text") or "").strip(), item.get("text"))} for item in items]
        for key, items in feedback_lists.items()
    }
    return {**intelligence, "insights": {**insights, **localized_lists}}
