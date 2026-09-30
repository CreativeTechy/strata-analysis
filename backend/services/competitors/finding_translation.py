"""Locale-rendered view of one competitor finding's LLM-generated output
fields.

competitor_findings stays canonical English - generate_finding() writes it
once and nothing after that mutates headline/whats_up/impact/
confidence_reason/signals/actions (only validation_status/validation_notes
change, via set_finding_validation()). A viewer whose dashboard locale
differs from it gets that same content rendered into their locale on read,
generated once via the configured LLM and cached in
`competitor_finding_translations` rather than re-translated on every request -
same canonical-then-localized shape as services/articles/translation.py and
services/intelligence/trend_summary.py.

This only ever touches the *output* fields generate_finding() produced -
never the evidence rows (evidence[].title/.excerpt), which are the source
article's own text, not something an LLM call should be spent re-rendering.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, wait

import config
import db
from analysis.json_utils import JSONParseError, parse_json_response
from llm_client import chat_completion
from prompt_loader import load_prompt
from psycopg.types.json import Jsonb
from services.i18n.locales import language_instruction

logger = logging.getLogger(__name__)

TRANSLATION_SYSTEM_PROMPT = load_prompt("competitor_finding_translation_system_prompt.txt")

# Same rationale as services/articles/translation.py's _failure_cache: a
# failing/unreachable LLM provider must not cost a fresh
# LLM_REQUEST_TIMEOUT_SECONDS wait on every view of every finding in a
# non-default locale.
FAILURE_CACHE_SECONDS = 300
_failure_cache: dict[tuple[int, str], tuple[float, object]] = {}


def _recent_failure(finding_id: int, locale: str, source_generated_at) -> bool:
    entry = _failure_cache.get((finding_id, locale))
    if entry is None:
        return False
    failed_at, failed_source_generated_at = entry
    if failed_source_generated_at != source_generated_at:
        return False
    return (time.monotonic() - failed_at) < FAILURE_CACHE_SECONDS


def _record_failure(finding_id: int, locale: str, source_generated_at) -> None:
    _failure_cache[(finding_id, locale)] = (time.monotonic(), source_generated_at)


def _clear_failure(finding_id: int, locale: str) -> None:
    _failure_cache.pop((finding_id, locale), None)


TEXT_FIELDS = ("headline", "whats_up", "impact", "confidence_reason")


def _database_ready() -> bool:
    return bool(config.DATABASE_URL)


def _build_payload(finding: dict) -> dict:
    payload = {field: str(finding.get(field) or "") for field in TEXT_FIELDS}
    payload["signals"] = [str(s) for s in (finding.get("signals") or [])]
    payload["actions"] = [
        {"action": str((action or {}).get("action") or ""), "rationale": str((action or {}).get("rationale") or "")}
        for action in (finding.get("actions") or [])
    ]
    return payload


def _has_translatable_content(finding: dict) -> bool:
    payload = _build_payload(finding)
    return (
        any(payload[field].strip() for field in TEXT_FIELDS)
        or bool(payload["signals"])
        or bool(payload["actions"])
    )


def _apply_translation(finding: dict, translated: dict) -> dict:
    """Merge a translated payload (same shape _build_payload produces) back
    onto `finding`. A field the model dropped, retyped, or returned with a
    mismatched array length is left at its original (untranslated) value
    rather than risk pairing translated text with the wrong list item."""
    result = dict(finding)

    for field in TEXT_FIELDS:
        value = translated.get(field)
        if isinstance(value, str) and value.strip():
            result[field] = value

    original_signals = finding.get("signals") or []
    translated_signals = translated.get("signals")
    if isinstance(translated_signals, list) and len(translated_signals) == len(original_signals):
        result["signals"] = [str(v) for v in translated_signals]

    original_actions = finding.get("actions") or []
    translated_actions = translated.get("actions")
    if isinstance(translated_actions, list) and len(translated_actions) == len(original_actions):
        result["actions"] = [
            {
                **original,
                "action": str((translated_actions[i] or {}).get("action") or original.get("action") or ""),
                "rationale": str((translated_actions[i] or {}).get("rationale") or original.get("rationale") or ""),
            }
            for i, original in enumerate(original_actions)
        ]

    return result


def _load_cached(finding_id: int, locale: str) -> dict | None:
    if not _database_ready():
        return None
    return db.fetch_one(
        """
        select translated, source_generated_at
        from public.competitor_finding_translations
        where finding_id = %s and locale = %s
        """,
        (finding_id, locale),
    )


def _save_cached(finding_id: int, locale: str, translated: dict, source_generated_at) -> None:
    if not _database_ready():
        return
    db.execute(
        """
        insert into public.competitor_finding_translations
            (finding_id, locale, translated, source_generated_at, model)
        values (%s, %s, %s, %s, %s)
        on conflict (finding_id, locale) do update
           set translated = excluded.translated,
               source_generated_at = excluded.source_generated_at,
               model = excluded.model,
               updated_at = now()
        """,
        (finding_id, locale, Jsonb(translated), source_generated_at, config.COMPETITOR_LLM_CHAT_MODEL),
    )


def _translate_payload(finding: dict, locale: str) -> dict:
    payload = _build_payload(finding)
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


def localize_finding(finding: dict, *, locale: str, force: bool = False) -> dict:
    """Return `finding` (the row shape competitor_analysis.get_finding()/
    list_findings() return) with its output fields rendered into `locale`.

    A no-op for the default locale - the canonical version already is that
    locale. Otherwise: a cached translation is reused as long as it was
    rendered from this finding's current `generated_at` (findings are
    write-once, so this should never actually change, but the comparison is
    kept for the same defensive reason article_translations checks
    analyzed_at); a cache miss or `force=True` spends one LLM call to
    translate every output field together, then caches it. If that call
    fails, the canonical (default-locale) finding is returned instead of an
    error, tagged `locale_fallback: True` so the caller can say so - same
    fallback shape as localize_article_analysis()/generate_trend_summary()."""
    locale = locale or config.DEFAULT_LOCALE
    if locale == config.DEFAULT_LOCALE:
        return finding

    finding_id = int(finding["id"])
    if not _has_translatable_content(finding):
        return {**finding, "locale": locale}

    source_generated_at = finding.get("generated_at")

    if not force:
        cached = _load_cached(finding_id, locale)
        if cached is not None and (
            source_generated_at is None or cached.get("source_generated_at") == source_generated_at
        ):
            return {**_apply_translation(finding, cached["translated"]), "locale": locale, "cached": True}

        if _recent_failure(finding_id, locale, source_generated_at):
            return {**finding, "locale": config.DEFAULT_LOCALE, "locale_fallback": True}

    try:
        translated_payload = _translate_payload(finding, locale)
    except Exception:
        logger.exception("Finding translation failed for finding_id=%s locale=%s", finding_id, locale)
        _record_failure(finding_id, locale, source_generated_at)
        return {**finding, "locale": config.DEFAULT_LOCALE, "locale_fallback": True}

    _clear_failure(finding_id, locale)
    _save_cached(finding_id, locale, translated_payload, source_generated_at)
    return {**_apply_translation(finding, translated_payload), "locale": locale, "cached": False}


def localize_findings(findings: list[dict], *, locale: str) -> list[dict]:
    """Batch counterpart to localize_finding() for a whole findings list
    (list_findings()'s results, or get_finding()'s `history`).

    Runs the uncached translations through a small thread pool
    (config.COMPETITOR_ANALYSIS_CONCURRENCY workers) instead of one at a time,
    and stops starting new ones once config.FINDING_TRANSLATION_BUDGET_SECONDS
    has elapsed for this call - see that constant's own comment for why. A
    finding that was already cached, or that finishes within the budget, comes
    back translated exactly as localize_finding() would return it; a finding
    that never got submitted (the budget ran out before its turn) or is still
    running when the budget's `wait()` returns comes back as its canonical
    version tagged `locale_fallback: True`, same as an outright translation
    failure - a submitted-but-still-running call is left to finish on its own
    thread rather than cancelled, so it still populates the cache
    (localize_finding()'s own _save_cached) for whoever asks next."""
    locale = locale or config.DEFAULT_LOCALE
    if locale == config.DEFAULT_LOCALE or not findings:
        return findings

    deadline = time.monotonic() + config.FINDING_TRANSLATION_BUDGET_SECONDS
    results = list(findings)
    completed_indexes: set[int] = set()
    future_index: dict = {}

    max_workers = max(1, min(config.COMPETITOR_ANALYSIS_CONCURRENCY, len(findings)))
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        for index, finding in enumerate(findings):
            if time.monotonic() >= deadline:
                break
            future_index[pool.submit(localize_finding, finding, locale=locale)] = index

        if future_index:
            done, _pending = wait(future_index, timeout=max(deadline - time.monotonic(), 0))
            for future in done:
                index = future_index[future]
                results[index] = future.result()
                completed_indexes.add(index)
    finally:
        # wait=False: an in-flight translation is left running on its own
        # thread rather than blocked on here - blocking would defeat the
        # whole point of the deadline above.
        pool.shutdown(wait=False)

    if len(completed_indexes) < len(findings):
        logger.warning(
            "Finding translation budget (%ss) exceeded for locale=%s: %d/%d findings translated",
            config.FINDING_TRANSLATION_BUDGET_SECONDS, locale, len(completed_indexes), len(findings),
        )
    for index, finding in enumerate(findings):
        if index not in completed_indexes:
            results[index] = {**finding, "locale": config.DEFAULT_LOCALE, "locale_fallback": True}

    return results
