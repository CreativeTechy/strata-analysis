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

from collections import Counter

import db
from llm_client import chat_completion
from prompt_loader import load_prompt
from services.intelligence.intelligence import (
    _database_ready,
    _fetch_project_rows,
    filter_rows_for_period,
    normalize_period,
)

TREND_SUMMARY_SYSTEM_PROMPT = load_prompt("trend_summary_system_prompt.txt")

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


def generate_trend_summary(
    project: dict, period: str = "30d", run_id: str | None = None, force: bool = False,
) -> dict:
    period = normalize_period(period)
    project_id = project["id"]

    if not force:
        cached = _load_cached(project_id, period, run_id)
        if cached is not None:
            return cached

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
