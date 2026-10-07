"""Locale-rendered strings for the dashboard's "Top Ideas" widget
(insights.frequent_ideas inside get_project_intelligence()'s response).

Unlike article_translations/project_trend_summaries_localized/
competitor_finding_translations, there is no canonical row here to key
invalidation on: intelligence.py's frequent_ideas rollup is recomputed from
scratch on every request, for whatever (project_id, period, run_id) scope was
asked for. But a given idea's *text* doesn't depend on that scope - the same
recurring idea should translate the same way whichever period/run it's
counted in - so this caches by the idea text itself (per project + locale)
rather than by request scope. That also means the cache dedupes for free
across every period/run view once an idea's been translated once.
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

TRANSLATION_SYSTEM_PROMPT = load_prompt("idea_translation_system_prompt.txt")

# Same rationale as the other translation caches' _failure_cache: a failing/
# unreachable LLM provider must not cost a fresh LLM_REQUEST_TIMEOUT_SECONDS
# wait on every dashboard load for the same (project_id, locale).
FAILURE_CACHE_SECONDS = 300
_failure_cache: dict[tuple[int, str], float] = {}


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


def _load_cached(project_id: int, locale: str, ideas: list[str]) -> dict[str, str]:
    if not _database_ready() or not ideas:
        return {}
    rows = db.fetch_all(
        """
        select source_idea, translated_idea
        from public.project_frequent_idea_translations
        where project_id = %s and locale = %s and source_idea = any(%s)
        """,
        (project_id, locale, ideas),
    )
    return {row["source_idea"]: row["translated_idea"] for row in rows}


def _save_cached(project_id: int, locale: str, translations: dict[str, str]) -> None:
    if not _database_ready() or not translations:
        return
    for source_idea, translated_idea in translations.items():
        db.execute(
            """
            insert into public.project_frequent_idea_translations
                (project_id, locale, source_idea, translated_idea, model)
            values (%s, %s, %s, %s, %s)
            on conflict (project_id, locale, source_idea) do update
               set translated_idea = excluded.translated_idea,
                   model = excluded.model,
                   updated_at = now()
            """,
            (project_id, locale, source_idea, translated_idea, config.LLM_CHAT_MODEL),
        )


def _translate_ideas(ideas: list[str], locale: str) -> list[str]:
    raw = chat_completion(
        messages=[
            {"role": "system", "content": f"{TRANSLATION_SYSTEM_PROMPT}\n\n{language_instruction(locale)}"},
            {"role": "user", "content": json.dumps({"ideas": ideas}, ensure_ascii=False)},
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
    if not isinstance(translated, list) or len(translated) != len(ideas):
        raise RuntimeError("translation response has the wrong shape")
    return [str(v) for v in translated]


def localize_frequent_ideas(intelligence: dict, *, project_id: int, locale: str) -> dict:
    """Return `intelligence` (the shape get_project_intelligence() returns)
    with insights.frequent_ideas' `idea` text rendered into `locale`.

    A no-op for the default locale or an empty ideas list. Otherwise: ideas
    already cached for this project+locale are reused as-is; the remaining
    ideas are translated together in one LLM call and cached by their own
    text, not by (project_id, period, run_id) - see module docstring. An idea
    that fails to translate (a down provider, or the model dropping it) is
    left in its original English rather than blanked out or failing the whole
    dashboard load.
    """
    locale = locale or config.DEFAULT_LOCALE
    insights = intelligence.get("insights") if isinstance(intelligence.get("insights"), dict) else None
    if locale == config.DEFAULT_LOCALE or not insights:
        return intelligence

    # frequent_concerns is the dashboard's default "Top concerns" tab: a
    # separate (ranked-over-everything) list of the same kind of items.
    keys = [
        key for key in ("frequent_ideas", "frequent_concerns")
        if isinstance(insights.get(key), list) and insights[key]
    ]
    distinct_ideas = sorted({
        str(item.get("idea") or "").strip()
        for key in keys for item in insights[key] if item.get("idea")
    })
    if not distinct_ideas:
        return intelligence

    translations = _load_cached(project_id, locale, distinct_ideas)
    missing = [idea for idea in distinct_ideas if idea not in translations]

    if missing and not _recent_failure(project_id, locale):
        try:
            translated = _translate_ideas(missing, locale)
        except Exception:
            logger.exception("Idea translation failed for project_id=%s locale=%s", project_id, locale)
            _record_failure(project_id, locale)
        else:
            _clear_failure(project_id, locale)
            new_translations = dict(zip(missing, translated))
            _save_cached(project_id, locale, new_translations)
            translations.update(new_translations)

    # source_text keeps the original text alongside the translation: the
    # topic/evidence links search articles by it, and a translated string
    # would match nothing (same reason feedback_translation.py carries it).
    localized = {
        key: [
            {
                **item,
                "idea": translations.get(str(item.get("idea") or "").strip(), item.get("idea")),
                "source_text": item.get("idea"),
            }
            for item in insights[key]
        ]
        for key in keys
    }
    return {**intelligence, "insights": {**insights, **localized}}
