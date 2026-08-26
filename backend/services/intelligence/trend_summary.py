"""LLM-generated "overall trend" summary for a project's Reports page.

Kept separate from intelligence.py, which is pure deterministic aggregation -
this is the one place in that package that calls out to the configured LLM.
Nothing here is stored; like the rest of the intelligence endpoints, it's
recomputed live from whatever articles are in scope for the requested
period/run.
"""

from __future__ import annotations

from collections import Counter

from llm_client import chat_completion
from prompt_loader import load_prompt
from services.intelligence.intelligence import (
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


def generate_trend_summary(project: dict, period: str = "30d", run_id: str | None = None) -> dict:
    period = normalize_period(period)
    if run_id:
        rows = _fetch_project_rows(project["id"], run_id=run_id)
    else:
        rows = filter_rows_for_period(_fetch_project_rows(project["id"]), period)
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
    return {"summary": summary.strip(), "article_count": total, "period": period, "run_id": run_id}
