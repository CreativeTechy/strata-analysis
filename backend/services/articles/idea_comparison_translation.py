"""Locale-rendered strings for the dashboard's "Idea comparisons across
sources" cards (the list returned by idea_comparisons.list_idea_comparisons()).

The canonical comparison rows stay in the language they were generated in.
For another locale the idea title, the summary and each source's stated value
are translated and cached in `idea_comparison_text_translations`, keyed by a
hash of the source text per (project, locale) - the same cache-by-text shape
as services/intelligence/idea_translation.py, so a regenerate that leaves a
string unchanged keeps its cached translation and the cache dedupes across
run scopes. A string that fails to translate stays in its original language
rather than failing the whole card.
"""

from __future__ import annotations

import hashlib
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

# The idea-translation prompt already covers standalone short phrases and
# keeps names/numbers/units intact, which is what summaries and values need.
TRANSLATION_SYSTEM_PROMPT = load_prompt("idea_translation_system_prompt.txt")

# Same rationale as idea_translation's failure cache: an unreachable provider
# must not cost a fresh request timeout on every view.
FAILURE_CACHE_SECONDS = 300
_failure_cache: dict[tuple[int, str], float] = {}


def _recent_failure(project_id: int, locale: str) -> bool:
    failed_at = _failure_cache.get((project_id, locale))
    return failed_at is not None and (time.monotonic() - failed_at) < FAILURE_CACHE_SECONDS


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_cached(project_id: int, locale: str, texts: list[str]) -> dict[str, str]:
    if not config.DATABASE_URL or not texts:
        return {}
    by_hash = {_hash(text): text for text in texts}
    rows = db.fetch_all(
        """
        select source_hash, translated_text
        from public.idea_comparison_text_translations
        where project_id = %s and locale = %s and source_hash = any(%s)
        """,
        (project_id, locale, list(by_hash)),
    )
    return {by_hash[row["source_hash"]]: row["translated_text"] for row in rows if row["source_hash"] in by_hash}


def _save_cached(project_id: int, locale: str, translations: dict[str, str]) -> None:
    if not config.DATABASE_URL:
        return
    for source, translated in translations.items():
        db.execute(
            """
            insert into public.idea_comparison_text_translations
                (project_id, locale, source_hash, translated_text, model)
            values (%s, %s, %s, %s, %s)
            on conflict (project_id, locale, source_hash) do update
               set translated_text = excluded.translated_text,
                   model = excluded.model,
                   updated_at = now()
            """,
            (project_id, locale, _hash(source), translated, config.LLM_CHAT_MODEL),
        )


def _translate(texts: list[str], locale: str) -> list[str]:
    raw = chat_completion(
        messages=[
            {"role": "system", "content": f"{TRANSLATION_SYSTEM_PROMPT}\n\n{language_instruction(locale)}"},
            {"role": "user", "content": json.dumps({"ideas": texts}, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=4000,
        json_mode=True,
    )
    if raw is None:
        raise RuntimeError("translation model unavailable")
    try:
        parsed = parse_json_response(raw)
    except JSONParseError as exc:
        raise RuntimeError(f"invalid translation JSON: {exc}") from exc
    translated = parsed.get("ideas") if isinstance(parsed, dict) else None
    if not isinstance(translated, list) or len(translated) != len(texts):
        raise RuntimeError("translation response has the wrong shape")
    return [str(v) for v in translated]


def _strings_of(comparison: dict) -> list[str]:
    values = [comparison.get("idea"), comparison.get("summary")]
    values += [source.get("value") for source in comparison.get("sources") or []]
    return [str(v).strip() for v in values if v and str(v).strip()]


def _apply(comparison: dict, translations: dict[str, str]) -> dict:
    def tr(value):
        return translations.get(str(value).strip(), value) if value else value

    localized = {**comparison, "idea": tr(comparison.get("idea")), "summary": tr(comparison.get("summary"))}
    if "sources" in comparison:
        localized["sources"] = [{**s, "value": tr(s.get("value"))} for s in comparison.get("sources") or []]
    return localized


CHUNK_SIZE = 8


def _translate_chunked(texts: list[str], locale: str, *, fail_fast: bool = False) -> dict[str, str]:
    """Translate in small chunks so one long excerpt can't sink the batch; a
    chunk the model answers with the wrong shape is retried item by item.
    Returns only what was translated - a failing item simply stays absent.
    `fail_fast` (for a caller blocking a request, e.g. the report export)
    skips the item-by-item retry and stops at the first failing chunk, so a
    slow or hung model costs one timeout rather than one per string."""
    result: dict[str, str] = {}
    for start in range(0, len(texts), CHUNK_SIZE):
        chunk = texts[start:start + CHUNK_SIZE]
        try:
            result.update(zip(chunk, _translate(chunk, locale)))
            continue
        except Exception:
            if fail_fast:
                logger.warning("Idea comparison chunk translation failed (%d items); giving up (fail fast)", len(chunk))
                break
            logger.warning("Idea comparison chunk translation failed (%d items); retrying one by one", len(chunk))
        for text in chunk:
            try:
                result[text] = _translate([text], locale)[0]
            except Exception:
                logger.exception("Idea comparison translation failed for one text")
    return result


def _translate_missing(texts: list[str], *, project_id: int, locale: str, fail_fast: bool = False) -> dict[str, str]:
    """text -> translation for every text in `texts`: cached ones as-is, the
    rest translated in one LLM call and cached. Texts that fail stay absent."""
    translations = _load_cached(project_id, locale, texts)
    missing = [text for text in texts if text not in translations]
    if missing and not _recent_failure(project_id, locale):
        new = _translate_chunked(missing, locale, fail_fast=fail_fast)
        if new:
            _failure_cache.pop((project_id, locale), None)
            _save_cached(project_id, locale, new)
            translations.update(new)
        else:
            logger.error("Idea comparison translation failed for project_id=%s locale=%s", project_id, locale)
            _failure_cache[(project_id, locale)] = time.monotonic()
    return translations


def localize_idea_comparisons(comparisons: list[dict], *, project_id: int, locale: str) -> list[dict]:
    """Return `comparisons` with idea/summary/source values rendered into
    `locale`. A no-op for the default locale or an empty list."""
    locale = locale or config.DEFAULT_LOCALE
    if locale == config.DEFAULT_LOCALE or not comparisons:
        return comparisons
    distinct = sorted({text for comparison in comparisons for text in _strings_of(comparison)})
    translations = _translate_missing(distinct, project_id=project_id, locale=locale)
    return [_apply(comparison, translations) for comparison in comparisons]


def translate_texts(texts: list[str], *, project_id: int, locale: str) -> dict[str, str]:
    """text -> translation for free-standing strings (e.g. the report's top
    article titles and summaries), sharing this module's per-text cache. A
    no-op ({}) for the default locale; a text that fails to translate is
    simply absent so the caller keeps the original. Fails fast (one timeout,
    no per-item retries) because the report export waits on it."""
    locale = locale or config.DEFAULT_LOCALE
    distinct = sorted({str(t).strip() for t in texts if t and str(t).strip()})
    if locale == config.DEFAULT_LOCALE or not distinct:
        return {}
    return _translate_missing(distinct, project_id=project_id, locale=locale, fail_fast=True)


def _detail_strings(comparison: dict) -> list[str]:
    values = [comparison.get("idea"), comparison.get("summary")]
    for source in comparison.get("sources") or []:
        values += [source.get("title"), source.get("excerpt"), source.get("value")]
    for fact in comparison.get("facts") or []:
        values += [fact.get("fact_text"), fact.get("stated_value")]
    for group in (comparison.get("numeric_evidence") or {}).get("groups") or []:
        values.append(group.get("metric"))
        values += [item.get("metric") for item in group.get("observations") or []]
    return [str(v).strip() for v in values if v and str(v).strip()]


def localize_idea_comparison_detail(comparison: dict, *, project_id: int, locale: str) -> dict:
    """Detail-page counterpart of localize_idea_comparisons(): also renders
    each source's title/excerpt, the user-added facts' text and the numeric
    evidence's metric names. Source labels, URLs, units and periods are left
    alone."""
    locale = locale or config.DEFAULT_LOCALE
    if locale == config.DEFAULT_LOCALE or not comparison:
        return comparison
    translations = _translate_missing(sorted(set(_detail_strings(comparison))), project_id=project_id, locale=locale)

    def tr(value):
        return translations.get(str(value).strip(), value) if value else value

    localized = _apply(comparison, translations)
    localized["sources"] = [
        {**s, "title": tr(s.get("title")), "excerpt": tr(s.get("excerpt"))} for s in localized.get("sources") or []
    ]
    localized["facts"] = [
        # The originals ride along: an edit form must start from the canonical
        # text, never from the rendered translation.
        {**f, "fact_text": tr(f.get("fact_text")), "stated_value": tr(f.get("stated_value")),
         "fact_text_original": f.get("fact_text"), "stated_value_original": f.get("stated_value")}
        for f in comparison.get("facts") or []
    ]
    evidence = comparison.get("numeric_evidence") or {}
    if evidence.get("groups"):
        localized["numeric_evidence"] = {**evidence, "groups": [
            {**g, "metric": tr(g.get("metric")),
             "observations": [{**o, "metric": tr(o.get("metric"))} for o in g.get("observations") or []]}
            for g in evidence["groups"]
        ]}
    return localized
