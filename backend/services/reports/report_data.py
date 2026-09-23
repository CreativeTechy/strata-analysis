"""Builds the single report-data snapshot every section of the Reports page's
Export Summary PDF is rendered from (services/reports/pdf_renderer.py) and
that yesterday_comparison.py's "today" side reuses - one query, one set of
counts/percentages, so the PDF can never show a different total or sentiment
mix than the numbers it derived them from.

Deliberately separate from services/intelligence/intelligence.py: that module
feeds the live Reports page (StatsOverview.jsx) and several of its callers
(the dashboard, keyword existence) need a different row shape than this does
(relevance_score/analysis_status/topics/key_points, absent from
intelligence._fetch_project_rows' column list). Extending that shared query
for one PDF-only need would touch every other reader of it for no benefit -
see article_analyses.fetch_run_article_rows, which already got the same
additive columns for exactly this reason.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import config
import db
from services.articles.article_analyses import fetch_run_article_rows
from services.intelligence.intelligence import (
    VALID_SENTIMENTS,
    article_date,
    filter_rows_for_period,
    net_sentiment,
    normalize_period,
)
from services.intelligence.trend_summary import generate_trend_summary

SHORT_SUMMARY_MAX_CHARS = 280

# analysis_status values that mean "has a real, non-placeholder analysis" -
# see schema.sql's articles_analysis_status_check. 'partial' is intentionally
# excluded from the analyzed/sentiment bucket even though it's not a total
# failure: structured extraction only partially completed, so trusting its
# sentiment the same as a clean 'success' would risk exactly the "neutral
# placeholder counted as a real reading" this requirement calls out.
ANALYZED_STATUSES = {"success"}
PENDING_STATUSES = {"pending", "processing"}
FAILED_STATUSES = {"failed", "partial"}


def report_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(config.REPORT_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def _source_label(row: dict) -> str:
    """Matches CLAUDE.md: an approved document candidate's article gets
    `source` = the document's filename, so that's the "source document" this
    report shows whenever present. Falls back to the URL host for an article
    that didn't come from a document (a JSONL import carrying a real URL)."""
    source = str(row.get("source") or "").strip()
    if source:
        return source
    for candidate in (row.get("source_url"), row.get("url")):
        text = str(candidate or "").strip()
        if not text or text.startswith("document://"):
            continue
        host = urlparse(text).netloc.strip().lower()
        if host:
            return host[4:] if host.startswith("www.") else host
    return "Unknown source"

def _short_summary(row: dict) -> str:
    text = str(row.get("summary") or "").strip()
    if len(text) <= SHORT_SUMMARY_MAX_CHARS:
        return text
    return text[:SHORT_SUMMARY_MAX_CHARS].rsplit(" ", 1)[0] + "..."


def _fetch_period_rows(project_id: int) -> list[dict]:
    """Every article in the project, regardless of analysis_status - the
    report's total/pending/failed counts need the whole population, not just
    the successfully analyzed subset filter_rows_for_period narrows later."""
    return db.fetch_all(
        """
        select a.id, a.url, a.source, a.source_url, a.title, a.summary,
               a.sentiment, a.relevance_score, a.analysis_status,
               a.topics, a.key_points, a.insight_json,
               a.published, a.created_at
        from articles a
        join article_projects ap on ap.article_id = a.id
        where ap.project_id = %s
        """,
        (int(project_id),),
    ) or []


def _status_counts(rows: list[dict]) -> dict:
    counts = Counter(str(row.get("analysis_status") or "pending").lower() for row in rows)
    return {
        "total": len(rows),
        "analyzed": sum(counts[s] for s in ANALYZED_STATUSES),
        "pending": counts.get("pending", 0),
        "processing": counts.get("processing", 0),
        "failed": counts.get("failed", 0),
        "partial": counts.get("partial", 0),
    }


def _sentiment_breakdown(analyzed_rows: list[dict]) -> dict:
    """Only ever called with analysis_status=='success' rows - a pending or
    failed article's `sentiment` column still holds DEFAULT_ENRICHMENT's
    'neutral' placeholder (see analysis_defaults.py), which must not be
    counted as a real reading."""
    counts = Counter(str(row.get("sentiment") or "").lower() for row in analyzed_rows)
    total = len(analyzed_rows)
    result = {}
    for key in ("positive", "negative", "neutral", "mixed"):
        count = int(counts.get(key, 0))
        result[key] = {"count": count, "pct": round((count / total) * 100, 1) if total else 0.0}
    result["net_sentiment"] = net_sentiment(counts, total)
    result["analyzed_total"] = total
    return result


def _rank_key(row: dict, fallback: bool):
    if fallback:
        date = article_date(row) or datetime.min.replace(tzinfo=timezone.utc)
        return (date, int(row.get("id") or 0))
    score = row.get("relevance_score")
    score = float(score) if score is not None else float("-inf")
    date = article_date(row) or datetime.min.replace(tzinfo=timezone.utc)
    return (score, date, int(row.get("id") or 0))


def _top_articles(analyzed_rows: list[dict], limit: int) -> tuple[list[dict], bool]:
    """Rank by relevance_score (desc), tie-broken by published date (desc,
    missing dates sort last) then article id (desc) for a fully deterministic
    order. Falls back to plain recency when relevance_score is missing on
    every candidate - a project whose analysis pipeline never populated it
    still gets a "top articles" section instead of an arbitrary one, clearly
    labeled per-article so the PDF can disclose it rather than passing it off
    as a real relevance ranking."""
    if not analyzed_rows:
        return [], False

    has_scores = any(row.get("relevance_score") is not None for row in analyzed_rows)
    ordered = sorted(analyzed_rows, key=lambda row: _rank_key(row, fallback=not has_scores), reverse=True)
    top = ordered[:limit]

    articles = []
    for rank, row in enumerate(top, start=1):
        score = row.get("relevance_score")
        articles.append({
            "rank": rank,
            "article_id": row.get("id"),
            "title": str(row.get("title") or "").strip() or "(untitled)",
            "short_summary": _short_summary(row),
            "sentiment": str(row.get("sentiment") or "neutral").lower(),
            "source": _source_label(row),
            "reference": f"/articles/{row.get('id')}",
            "relevance_score": float(score) if score is not None else None,
            "ranking_method": "relevance_score" if has_scores else "fallback_recency",
        })
    return articles, not has_scores


def _stale_executive_summary(cached: dict | None, rows: list[dict]) -> bool:
    """Whether the cached trend summary predates the newest analysis in
    scope - i.e. an article was (re)analyzed after the cached paragraph was
    written, so its "article_count matched" cache is stale even though the
    count itself may not have changed (a reanalysis can change sentiment/
    content without changing how many articles are in scope)."""
    if not cached or not cached.get("cached"):
        return False
    generated_at = cached.get("generated_at")
    if not generated_at:
        return True
    try:
        cached_at = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if not cached_at.tzinfo:
        cached_at = cached_at.replace(tzinfo=timezone.utc)
    newest = None
    for row in rows:
        candidate = article_date(row)
        if candidate and (newest is None or candidate > newest):
            newest = candidate
    return bool(newest and newest > cached_at)


def _scope_label(scope_type: str, period: str | None, run: dict | None, tz: ZoneInfo) -> tuple[str, str]:
    """(analysis_date_label, run_label)."""
    if scope_type == "run" and run:
        sequence = run.get("sequence_number")
        when = run.get("finished_at") or run.get("created_at")
        run_label = f"Pipeline #{sequence}" if sequence else "Analysis run"
        when_label = when.astimezone(tz).strftime("%b %d, %Y") if isinstance(when, datetime) else "unknown date"
        return f"{run_label} - {when_label}", run_label
    period_labels = {"7d": "Last 7 days", "30d": "Last 30 days", "all": "All time"}
    today = datetime.now(tz).strftime("%b %d, %Y")
    label = period_labels.get(normalize_period(period), "Last 30 days")
    return f"{label} (through {today})", None


def build_report_data(project: dict, period: str | None = None, run: dict | None = None) -> dict:
    """`run`, when given, is the already-fetched-and-ownership-validated
    pipeline_runs row (see main.py's endpoint) - this function trusts it
    belongs to `project` rather than re-checking."""
    tz = report_timezone()
    project_id = project["id"]
    scope_type = "run" if run else "period"

    if scope_type == "run":
        all_rows = fetch_run_article_rows(project_id, run["id"])
        in_scope_rows = all_rows
    else:
        all_rows = _fetch_period_rows(project_id)
        in_scope_rows = filter_rows_for_period(all_rows, normalize_period(period))

    analyzed_rows = [row for row in in_scope_rows if str(row.get("analysis_status") or "").lower() in ANALYZED_STATUSES]

    analysis_date_label, run_label = _scope_label(scope_type, period, run, tz)

    cached_summary = generate_trend_summary(project, normalize_period(period or "30d"), run_id=(run["id"] if run else None))
    if _stale_executive_summary(cached_summary, analyzed_rows):
        cached_summary = generate_trend_summary(
            project, normalize_period(period or "30d"), run_id=(run["id"] if run else None), force=True,
        )

    top_articles, fallback_used = _top_articles(analyzed_rows, config.REPORT_TOP_ARTICLES_LIMIT)

    return {
        "project": {"id": project_id, "name": project.get("name") or f"Project {project_id}"},
        "scope": {
            "type": scope_type,
            "period": normalize_period(period) if scope_type == "period" else None,
            "run_id": run["id"] if run else None,
            "run_label": run_label,
            "analysis_date_label": analysis_date_label,
            "timezone": config.REPORT_TIMEZONE,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": _status_counts(in_scope_rows),
        "sentiment": _sentiment_breakdown(analyzed_rows),
        "executive_summary": {
            "text": (cached_summary or {}).get("summary"),
            "cached": bool((cached_summary or {}).get("cached")),
        },
        "top_articles": top_articles,
        "top_articles_fallback_used": fallback_used,
        # Internal only - consumed by yesterday_comparison.py, not rendered
        # directly (see pdf_renderer.py's contract, which only takes the
        # public keys above plus a separately-built `comparison` dict).
        "_analyzed_rows": analyzed_rows,
    }
