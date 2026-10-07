"""Locale-rendered project names for the dashboard (project pickers, headers,
lists). Adds a `display_name` next to each project's canonical `name`; `name`
itself is never touched, so edit forms and exports keep the operator's text.

Cached per (project_id, locale, source_name) - see migration 0052 - so a
rename misses the cache and re-translates. A failure leaves `display_name`
equal to the original name rather than failing the project list.
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

TRANSLATION_SYSTEM_PROMPT = load_prompt("project_name_translation_system_prompt.txt")

# A down LLM must not cost a request timeout on every project-list load.
FAILURE_CACHE_SECONDS = 300
# Names per LLM call, so the response always fits max_tokens however many
# projects are uncached; each chunk is cached on its own.
TRANSLATION_BATCH_SIZE = 20
_failure_cache: dict[str, float] = {}


def _recent_failure(locale: str) -> bool:
    failed_at = _failure_cache.get(locale)
    return failed_at is not None and (time.monotonic() - failed_at) < FAILURE_CACHE_SECONDS


def _load_cached(locale: str, pairs: list[tuple[int, str]]) -> dict[tuple[int, str], str]:
    if not config.DATABASE_URL or not pairs:
        return {}
    rows = db.fetch_all(
        """
        select project_id, source_name, translated_name
        from public.project_name_translations
        where locale = %s and project_id = any(%s)
        """,
        (locale, sorted({pid for pid, _ in pairs})),
    )
    wanted = set(pairs)
    return {
        (row["project_id"], row["source_name"]): row["translated_name"]
        for row in rows
        if (row["project_id"], row["source_name"]) in wanted
    }


def _save_cached(locale: str, translations: dict[tuple[int, str], str]) -> None:
    if not config.DATABASE_URL:
        return
    for (project_id, source_name), translated in translations.items():
        db.execute(
            """
            insert into public.project_name_translations
                (project_id, locale, source_name, translated_name, model)
            values (%s, %s, %s, %s, %s)
            on conflict (project_id, locale, source_name) do update
               set translated_name = excluded.translated_name,
                   model = excluded.model,
                   updated_at = now()
            """,
            (project_id, locale, source_name, translated, config.LLM_CHAT_MODEL),
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


def localize_project_names(projects: list[dict], *, locale: str) -> list[dict]:
    """Return `projects` with a `display_name` on each: the name rendered into
    `locale`, or the original name for the default locale / on failure."""
    locale = locale or config.DEFAULT_LOCALE
    result = [{**p, "display_name": p.get("name")} for p in projects]
    if locale == config.DEFAULT_LOCALE:
        return result

    pairs = [
        (p["id"], str(p["name"]).strip())
        for p in projects
        if p.get("id") is not None and str(p.get("name") or "").strip()
    ]
    if not pairs:
        return result

    translations = _load_cached(locale, pairs)
    missing = [pair for pair in pairs if pair not in translations]

    if missing and not _recent_failure(locale):
        distinct = sorted({name for _, name in missing})
        for start in range(0, len(distinct), TRANSLATION_BATCH_SIZE):
            chunk = distinct[start:start + TRANSLATION_BATCH_SIZE]
            try:
                translated = dict(zip(chunk, _translate_names(chunk, locale)))
            except Exception:
                logger.exception("Project name translation failed for locale=%s", locale)
                _failure_cache[locale] = time.monotonic()
                break
            new = {pair: translated[pair[1]] for pair in missing if pair[1] in translated}
            _save_cached(locale, new)
            translations.update(new)
        else:
            _failure_cache.pop(locale, None)

    for item in result:
        key = (item.get("id"), str(item.get("name") or "").strip())
        if key in translations:
            item["display_name"] = translations[key]
    return result
