"""Builds the single report-data snapshot every section of the Reports page's
Export Summary PDF is rendered from (services/reports/pdf_renderer.py) and
that the run comparison's selected-run side reuses - one query, one set of
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

import logging
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import config
import db
from llm_client import LLMError
from services.articles import source_trust
from services.articles.article_analyses import fetch_run_article_rows
from services.articles.articles_query import source_group_identity
from services.articles.idea_comparisons import (
    generate_idea_comparisons,
    has_run_generation_attempt,
    list_idea_comparisons,
)
from services.intelligence.intelligence import (
    VALID_SENTIMENTS,
    article_date,
    filter_rows_for_period,
    net_sentiment,
    normalize_period,
)
from services.intelligence.trend_summary import generate_trend_summary

logger = logging.getLogger(__name__)

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
               a.sentiment_status, a.classification_status,
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


def _source_tiers(project_id: int, rows: list[dict]) -> dict:
    """article id -> {tier, is_default}, resolved exactly the way the Sources
    tab resolves it (same grouping key via source_group_identity, same
    override/default order via source_trust.resolve_many), so the PDF never
    shows a different tier than the page an operator sets it on. Only the
    tier itself is carried - an override's free-text reason can name another
    engagement, and a PDF gets forwarded far more readily than a page view.
    One resolve for every row rather than one per article."""
    groups: dict[str, dict] = {}
    article_keys: dict = {}
    for row in rows:
        key, source_type, label, _link = source_group_identity(row.get("url"), row.get("source"), row.get("source_url"))
        groups.setdefault(key, {"key": key, "type": source_type, "label": label})
        article_keys[row.get("id")] = key
    try:
        resolved = source_trust.resolve_many(list(groups.values()), project_id=project_id)
    except Exception:
        logger.exception("Report source trust-tier lookup failed")
        resolved = {}
    result = {}
    for article_id, key in article_keys.items():
        entry = resolved.get(key) or {}
        tier = entry.get("tier") if entry.get("tier") in source_trust.TIERS else "unknown"
        result[article_id] = {"tier": tier, "is_default": bool(entry.get("is_default", True))}
    return result


def _fetch_article_identities(article_ids: list) -> dict:
    ids = sorted({int(i) for i in article_ids if i is not None})
    if not ids:
        return {}
    rows = db.fetch_all(
        "select id, url, source, source_url from articles where id = any(%s)",
        (ids,),
    ) or []
    return {row["id"]: row for row in rows}


def _idea_comparisons(project_id: int, run_id: str | None) -> dict:
    """The cross-source idea comparisons (services/articles/idea_comparisons.py)
    for the report's scope, each source's stated value surfaced as that
    source's claim, with the source's trust tier beside it.

    Reads the cache the same way /idea-comparisons does, including its lazy
    first-view generation for a run scope - an export is often the first
    time a given run's comparisons are ever asked for. The project-wide
    cache has no period filter of its own (idea clusters are cumulative), so
    a period-scoped report says so rather than implying they were cut to the
    period. An LLM failure degrades this section to whatever was already
    cached plus a disclosed error, the same as the executive summary."""
    comparisons: list[dict] = []
    error = None
    try:
        comparisons = list_idea_comparisons(project_id, run_id=run_id)
        if run_id and not has_run_generation_attempt(project_id, run_id):
            generate_idea_comparisons(project_id, run_id=run_id)
            comparisons = list_idea_comparisons(project_id, run_id=run_id)
    except LLMError as e:
        logger.warning("Report idea comparison generation failed (%s): %s", e.code, e.detail or e)
        error = e.user_message
    except Exception:
        logger.exception("Report idea comparisons failed unexpectedly")
        error = "Something went wrong while loading idea comparisons."

    article_ids = [s.get("article_id") for c in comparisons for s in (c.get("sources") or [])]
    try:
        identities = _fetch_article_identities(article_ids)
    except Exception:
        logger.exception("Report idea comparison source lookup failed")
        identities = {}
    tiers = _source_tiers(project_id, list(identities.values()))

    items = []
    for comparison in comparisons:
        claims = []
        for source in comparison.get("sources") or []:
            article_id = source.get("article_id")
            identity = identities.get(article_id)
            claims.append({
                "source": _source_label(identity) if identity else (source.get("source_label") or "Unknown source"),
                "source_tier": tiers.get(article_id) or {"tier": "unknown", "is_default": True},
                "claim": str(source.get("value") or "").strip() or None,
                "article_id": article_id,
                "title": str(source.get("title") or "").strip() or "(untitled)",
                "reference": f"/articles/{article_id}" if article_id is not None else "",
            })
        items.append({
            "idea": comparison.get("idea") or "",
            "type": comparison.get("type"),
            "diverges": bool(comparison.get("diverges")),
            "summary": comparison.get("summary"),
            "claims": claims,
        })

    return {"items": items, "error": error, "project_wide": run_id is None}


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


def _safe_generate_trend_summary(project: dict, period: str, run_id: str | None, force: bool = False) -> dict:
    """generate_trend_summary() calls out to the configured LLM with no
    internal error handling of its own (main.py's /trend-summary route wraps
    it in exactly this try/except) - a provider outage is the most common
    failure mode for a local model (see CLAUDE.md), and it must degrade the
    executive-summary section of the PDF, not take down the whole export the
    way an unguarded call here used to. Shaped like generate_trend_summary's
    own return value, with `error`/`error_code` added on failure."""
    try:
        return generate_trend_summary(project, period, run_id=run_id, force=force)
    except LLMError as e:
        logger.warning("Report executive summary generation failed (%s): %s", e.code, e.detail or e)
        return {"summary": None, "cached": False, "error": e.user_message, "error_code": e.code}
    except Exception:
        logger.exception("Report executive summary generation failed unexpectedly")
        return {
            "summary": None, "cached": False,
            "error": "Something went wrong while generating the executive summary.",
            "error_code": "llm_provider_error",
        }


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
    sentiment_rows = [
        row for row in analyzed_rows
        if row.get("sentiment_status") == "ran" or "sentiment_status" not in row
    ]

    analysis_date_label, run_label = _scope_label(scope_type, period, run, tz)

    cached_summary = _safe_generate_trend_summary(project, normalize_period(period or "30d"), run_id=(run["id"] if run else None))
    if _stale_executive_summary(cached_summary, analyzed_rows):
        refreshed = _safe_generate_trend_summary(
            project, normalize_period(period or "30d"), run_id=(run["id"] if run else None), force=True,
        )
        # Keep the stale-but-real paragraph rather than discarding it for
        # nothing at all when the forced refresh itself fails (e.g. the same
        # LLM outage that made the first call above return an error too).
        if refreshed.get("summary") is not None:
            cached_summary = refreshed

    top_articles, fallback_used = _top_articles(analyzed_rows, config.REPORT_TOP_ARTICLES_LIMIT)
    top_ids = {item["article_id"] for item in top_articles}
    tiers = _source_tiers(project_id, [row for row in analyzed_rows if row.get("id") in top_ids])
    for item in top_articles:
        item["source_tier"] = tiers.get(item["article_id"]) or {"tier": "unknown", "is_default": True}

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
        "sentiment": {
            **_sentiment_breakdown(sentiment_rows),
            "articles_total": len(in_scope_rows),
            "not_assessed": len(in_scope_rows) - len(sentiment_rows),
        },
        "executive_summary": {
            "text": (cached_summary or {}).get("summary"),
            "cached": bool((cached_summary or {}).get("cached")),
            "error": (cached_summary or {}).get("error"),
        },
        "top_articles": top_articles,
        "top_articles_fallback_used": fallback_used,
        "idea_comparisons": _idea_comparisons(project_id, run["id"] if run else None),
        # Internal only - consumed by the last-run comparison, not rendered
        # directly (see pdf_renderer.py's contract, which only takes the
        # public keys above plus a separately-built `comparison` dict).
        "_analyzed_rows": analyzed_rows,
    }
