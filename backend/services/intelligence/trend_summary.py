"""LLM-generated "overall trend" summary for a project's Reports page.

Kept separate from intelligence.py, which is pure deterministic aggregation -
this is the one place in that package that calls out to the configured LLM.

Unlike the rest of the intelligence endpoints, the result *is* stored (in
`project_trend_summaries`, keyed by project/period/run scope) rather than
recomputed on every page load - an LLM call on every Reports view would burn
tokens for no benefit when the underlying articles haven't changed. A cache
hit is returned as-is; regeneration only happens when nothing is cached yet
for that scope, or the caller explicitly asks for it (the Reports page's
refresh button).
"""

from __future__ import annotations

import logging
from collections import Counter

import config
import db
from llm_client import chat_completion
from prompt_loader import load_prompt
from services.i18n.locales import language_instruction
from services.intelligence.intelligence import (
    _database_ready,
    _fetch_project_rows,
    filter_rows_for_period,
    normalize_period,
)

TREND_SUMMARY_SYSTEM_PROMPT = load_prompt("trend_summary_system_prompt.txt")

# One extra LLM call to render the already-generated canonical (English)
# summary into a non-default locale, rather than re-deriving it from the raw
# articles - the canonical summary is what search/grouping/comparison stay
# keyed on, so a localized read is a rendering of that same text, not a
# second, independently-generated analysis of the same articles.
LOCALIZED_TREND_SUMMARY_SYSTEM_PROMPT = (
    "You render an already-written analyst summary into another language for "
    "display purposes only. Preserve every fact, number, and the overall "
    "structure exactly - this is a translation, not a new analysis. Keep "
    "proper names, organization names, and any directly quoted material "
    "exactly as given rather than translating them. Output only the "
    "rendered summary text, with no preamble."
)

logger = logging.getLogger(__name__)

# Feeding every article in a large project into one prompt would blow past
# context limits long before it added useful signal - sample evenly across
# the chronological range instead of truncating, so the trend read still
# covers how things end, not just how they started.
MAX_ARTICLES = 100


def _article_summary(row: dict) -> str:
    return str(row.get("summary") or (row.get("insight_json") or {}).get("summary") or "").strip()


def _sample_chronological(rows: list[dict], limit: int) -> list[dict]:
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    return [rows[int(i * step)] for i in range(limit)]


def _project_context_line(project: dict) -> str:
    name = str(project.get("name") or "").strip()
    keywords = [str(k).strip() for k in (project.get("keywords") or []) if str(k or "").strip()]
    parts = [f"Project: {name}"] if name else []
    if keywords:
        parts.append(f"Topics of interest: {', '.join(keywords)}")
    return " | ".join(parts)


def _load_cached(project_id: int, period: str, run_id: str | None) -> dict | None:
    if not _database_ready():
        return None
    row = db.fetch_one(
        """
        select summary, article_count, updated_at
        from public.project_trend_summaries
        where project_id = %s and period = %s and run_id = %s
        """,
        (project_id, period, run_id or ""),
    )
    if not row:
        return None
    return {
        "summary": row["summary"],
        "article_count": int(row["article_count"] or 0),
        "period": period,
        "run_id": run_id,
        "cached": True,
        "generated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


def _save_cached(project_id: int, period: str, run_id: str | None, summary: str, article_count: int) -> None:
    if not _database_ready():
        return
    db.execute(
        """
        insert into public.project_trend_summaries (project_id, period, run_id, summary, article_count)
        values (%s, %s, %s, %s, %s)
        on conflict (project_id, period, run_id) do update
           set summary = excluded.summary,
               article_count = excluded.article_count,
               updated_at = now()
        """,
        (project_id, period, run_id or "", summary, article_count),
    )


def _load_cached_localized(project_id: int, period: str, run_id: str | None, locale: str) -> dict | None:
    if not _database_ready():
        return None
    row = db.fetch_one(
        """
        select summary, source_updated_at, model, updated_at
        from public.project_trend_summaries_localized
        where project_id = %s and period = %s and run_id = %s and locale = %s
        """,
        (project_id, period, run_id or "", locale),
    )
    if not row:
        return None
    return row


def _save_cached_localized(
    project_id: int, period: str, run_id: str | None, locale: str, summary: str, source_updated_at, model: str | None,
) -> None:
    if not _database_ready():
        return
    db.execute(
        """
        insert into public.project_trend_summaries_localized
            (project_id, period, run_id, locale, summary, source_updated_at, model)
        values (%s, %s, %s, %s, %s, %s, %s)
        on conflict (project_id, period, run_id, locale) do update
           set summary = excluded.summary,
               source_updated_at = excluded.source_updated_at,
               model = excluded.model,
               updated_at = now()
        """,
        (project_id, period, run_id or "", locale, summary, source_updated_at, model),
    )


def _canonical_updated_at(project_id: int, period: str, run_id: str | None):
    """The canonical (English) row's own `updated_at` - the "source-analysis
    version" a localized row is checked against (see _load_cached_localized's
    caller) to decide whether it's stale."""
    if not _database_ready():
        return None
    row = db.fetch_one(
        """
        select updated_at from public.project_trend_summaries
        where project_id = %s and period = %s and run_id = %s
        """,
        (project_id, period, run_id or ""),
    )
    return row["updated_at"] if row else None


def _render_localized_summary(canonical_summary: str, locale: str) -> str:
    rendered = chat_completion(
        messages=[
            {
                "role": "system",
                "content": f"{LOCALIZED_TREND_SUMMARY_SYSTEM_PROMPT}\n\n{language_instruction(locale)}",
            },
            {"role": "user", "content": canonical_summary},
        ],
        temperature=0.0,
        max_tokens=1500,
    )
    return rendered.strip()


def generate_trend_summary(
    project: dict, period: str = "30d", run_id: str | None = None, force: bool = False,
    locale: str | None = None,
) -> dict:
    """Generate (or return the cached) trend summary.

    `locale` defaults to config.DEFAULT_LOCALE ("en"), the canonical language
    this summary has always been generated and cached in - that path is
    unchanged from before this parameter existed. A non-default locale is
    rendered from the canonical summary and cached separately (see
    `project_trend_summaries_localized`), keyed by the canonical row's own
    `updated_at` so a later canonical regeneration invalidates it - a stale
    localized row is simply re-rendered on the next request rather than ever
    being shown past its source's own change. If rendering fails, the
    canonical summary is returned instead of an error, tagged
    `locale_fallback: True` so the caller can say so."""
    locale = locale or config.DEFAULT_LOCALE
    period = normalize_period(period)
    project_id = project["id"]

    if locale == config.DEFAULT_LOCALE and not force:
        cached = _load_cached(project_id, period, run_id)
        if cached is not None:
            return cached

    if locale != config.DEFAULT_LOCALE:
        # The canonical (English) summary is the source of truth this is
        # rendered from - load it (generating it once if nothing is cached
        # yet), but never force-regenerate it just because a *localized*
        # regenerate was requested; `force` below only re-renders this
        # locale's own text from whatever canonical summary already exists.
        canonical = generate_trend_summary(
            project, period, run_id=run_id, force=False, locale=config.DEFAULT_LOCALE,
        )
        if not canonical.get("summary"):
            return canonical

        source_updated_at = _canonical_updated_at(project_id, period, run_id)

        if not force:
            localized = _load_cached_localized(project_id, period, run_id, locale)
            if localized is not None and (
                source_updated_at is None or localized["source_updated_at"] == source_updated_at
            ):
                return {
                    "summary": localized["summary"],
                    "article_count": canonical["article_count"],
                    "period": period,
                    "run_id": run_id,
                    "locale": locale,
                    "cached": True,
                    "generated_at": localized["updated_at"].isoformat() if localized["updated_at"] else None,
                }

        try:
            rendered = _render_localized_summary(canonical["summary"], locale)
        except Exception:
            logger.exception("Localized trend summary rendering failed for locale=%s", locale)
            return {**canonical, "locale": config.DEFAULT_LOCALE, "locale_fallback": True}

        _save_cached_localized(project_id, period, run_id, locale, rendered, source_updated_at, config.LLM_CHAT_MODEL)
        return {
            "summary": rendered,
            "article_count": canonical["article_count"],
            "period": period,
            "run_id": run_id,
            "locale": locale,
            "cached": False,
        }

    if run_id:
        rows = _fetch_project_rows(project_id, run_id=run_id)
    else:
        rows = filter_rows_for_period(_fetch_project_rows(project_id), period)
    rows = [row for row in rows if _article_summary(row)]

    total = len(rows)
    if total == 0:
        return {"summary": None, "article_count": 0, "period": period, "run_id": run_id}

    counts = Counter(str(row.get("sentiment") or "").lower() for row in rows)
    sentiment_line = ", ".join(
        f"{key}: {int(counts.get(key, 0))}" for key in ("positive", "negative", "neutral", "mixed")
    )

    sampled = _sample_chronological(rows, MAX_ARTICLES)
    corpus = "\n".join(
        f"{i + 1}. [{row.get('published') or row.get('created_at') or '?'} | {row.get('sentiment') or 'neutral'}] "
        f"{row.get('title') or ''}\n   {_article_summary(row)}"
        for i, row in enumerate(sampled)
    )

    project_context = _project_context_line(project)
    user_prompt = (
        (f"{project_context}\n\n" if project_context else "")
        + f"There are {total} analyzed items in the current view. Sentiment breakdown: {sentiment_line}.\n\n"
        + f"Items, oldest first:\n{corpus}"
    )

    summary = chat_completion(
        messages=[
            {"role": "system", "content": TREND_SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        # Generous relative to the few sentences actually wanted: a local
        # reasoning model (e.g. Qwen3 via Ollama) spends a hidden <think>
        # block ahead of the visible answer, and running out of budget mid-
        # thought means no visible answer at all - see llm_client._strip_reasoning.
        max_tokens=1500,
    )
    summary = summary.strip()
    _save_cached(project_id, period, run_id, summary, total)
    return {"summary": summary, "article_count": total, "period": period, "run_id": run_id, "cached": False}
