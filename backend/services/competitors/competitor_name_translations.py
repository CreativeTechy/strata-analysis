"""Locale-rendered competitor names for the competitor study screens.

Adds a display name next to each competitor's canonical name -
`display_name` on a competitor row, `competitor_display_name` on a finding,
`display_name` on a run's skipped entry. The canonical `name` /
`competitor_name` is never touched, so edit forms, matching, exports and the
PDF report keep the name the competitor was tracked under.

A company name is rendered the way it is written in the target language (its
established localized name, else a transliteration), not translated word for
word - which is why this has its own prompt rather than going through
services/i18n/label_translation.py.

Cached per (study, locale, source name) - see migration 0055 - so a rename
misses the cache and re-translates. A name that can't be rendered keeps its
original text rather than failing the page.
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

TRANSLATION_SYSTEM_PROMPT = load_prompt("competitor_name_translation_system_prompt.txt")

# Names per LLM call, so the response always fits max_tokens however many
# competitors are uncached; each batch is cached on its own.
TRANSLATION_BATCH_SIZE = 20

# A down LLM must not cost a request timeout on every competitor page load.
# Only a provider-level failure (FATAL_ANALYSIS_ERRORS) arms this - one batch
# the model mangled just leaves those names untranslated this time.
FAILURE_CACHE_SECONDS = 300
_failure_cache: dict[str, float] = {}


def _recent_failure(locale: str) -> bool:
    failed_at = _failure_cache.get(locale)
    return failed_at is not None and (time.monotonic() - failed_at) < FAILURE_CACHE_SECONDS


def _load_cached(project_id: int, locale: str, names: list[str]) -> dict[str, str]:
    if not config.DATABASE_URL or not names:
        return {}
    rows = db.fetch_all(
        """
        select source_name, translated_name
        from public.competitor_name_translations
        where project_id = %s and locale = %s and source_name = any(%s)
        """,
        (int(project_id), locale, names),
    )
    return {row["source_name"]: row["translated_name"] for row in rows}


def _save_cached(project_id: int, locale: str, translations: dict[str, str]) -> None:
    if not config.DATABASE_URL or not translations:
        return
    for source_name, translated in translations.items():
        db.execute(
            """
            insert into public.competitor_name_translations
                (project_id, locale, source_name, translated_name, model)
            values (%s, %s, %s, %s, %s)
            on conflict (project_id, locale, source_name) do update
               set translated_name = excluded.translated_name,
                   model = excluded.model,
                   updated_at = now()
            """,
            (int(project_id), locale, source_name, translated, config.LLM_CHAT_MODEL),
        )


def _translate_names(names: list[str], locale: str) -> list[str]:
    raw = chat_completion(
        messages=[
            {"role": "system", "content": f"{TRANSLATION_SYSTEM_PROMPT}\n\n{language_instruction(locale)}"},
            {"role": "user", "content": json.dumps({"names": names}, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=1000,
        json_mode=True,
    )
    if raw is None:
        raise RuntimeError("translation model unavailable")
    try:
        parsed = parse_json_response(raw)
    except JSONParseError as exc:
        raise RuntimeError(f"invalid translation JSON: {exc}") from exc
    translated = parsed.get("names") if isinstance(parsed, dict) else None
    if not isinstance(translated, list) or len(translated) != len(names):
        raise RuntimeError("translation response has the wrong shape")
    return [str(v).strip() or n for v, n in zip(translated, names)]


def translate_competitor_names(project_id: int, names, *, locale: str, force: bool = False) -> dict[str, str]:
    """{name: display name} for every non-blank name in `names` (competitors
    of study `project_id`). Identity for the default locale; otherwise cached
    names are reused and the rest rendered in batches. `force` is an explicit
    "translate these now" from the viewer: it ignores the provider-failure
    pause, so names that failed a moment ago are tried again."""
    distinct = sorted({str(name).strip() for name in names or [] if str(name or "").strip()})
    locale = locale or config.DEFAULT_LOCALE
    if locale == config.DEFAULT_LOCALE or not distinct:
        return {name: name for name in distinct}

    translations = _load_cached(project_id, locale, distinct)
    missing = [name for name in distinct if name not in translations]
    for start in range(0, len(missing), TRANSLATION_BATCH_SIZE):
        if not force and _recent_failure(locale):
            break
        batch = missing[start:start + TRANSLATION_BATCH_SIZE]
        try:
            new = dict(zip(batch, _translate_names(batch, locale)))
        except FATAL_ANALYSIS_ERRORS:
            logger.exception("Competitor name translation provider failed for locale=%s", locale)
            _failure_cache[locale] = time.monotonic()
            break
        except Exception:
            logger.warning("Competitor name batch failed for project=%s locale=%s, keeping source names",
                           project_id, locale, exc_info=True)
            continue
        _failure_cache.pop(locale, None)
        _save_cached(project_id, locale, new)
        translations.update(new)

    return {name: translations.get(name, name) for name in distinct}


def _display(translations: dict[str, str], name) -> str | None:
    if name is None:
        return None
    return translations.get(str(name).strip(), name)


def localize_competitors(project_id: int, competitors: list[dict], *, locale: str,
                         force: bool = False) -> list[dict]:
    """`competitors` (rows with a `name`) with a `display_name` on each."""
    translations = translate_competitor_names(
        project_id, [c.get("name") for c in competitors], locale=locale, force=force,
    )
    return [{**c, "display_name": _display(translations, c.get("name"))} for c in competitors]


def localize_finding_names(project_id: int, findings: list[dict], *, locale: str) -> list[dict]:
    """`findings` (rows with a `competitor_name`, all from study `project_id`)
    with a `competitor_display_name` on each."""
    translations = translate_competitor_names(
        project_id, [f.get("competitor_name") for f in findings], locale=locale,
    )
    return [{**f, "competitor_display_name": _display(translations, f.get("competitor_name"))} for f in findings]
