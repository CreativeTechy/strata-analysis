"""On-demand (re)analysis for already-scraped articles.

This is the single/batch "run the analysis pipeline on this article again"
path used by the FastAPI layer (main.py) - distinct from pipeline.py's
scrape -> enrich -> save subprocess pipeline. It runs in-process (called via
FastAPI BackgroundTasks) since it's a lightweight, per-article job that
doesn't need subprocess isolation or cancellation the way a multi-stage
crawl does.
"""

from __future__ import annotations

from datetime import datetime, timezone

import db
from analysis.orchestrator import analyze_article
from store import save_articles

ARTICLE_SOURCE_FIELDS = ("id", "url", "source", "source_url", "title", "author", "published", "text")


def load_article_for_reanalysis(article_id: int) -> dict | None:
    return db.fetch_one(
        "select {} from articles where id = %s".format(", ".join(ARTICLE_SOURCE_FIELDS)),
        (article_id,),
    )


def mark_processing(article_id: int) -> None:
    """Best-effort - if analysis_status doesn't exist yet (pre-migration),
    this silently no-ops rather than blocking the reanalysis itself."""
    try:
        db.execute(
            "update articles set analysis_status = 'processing' where id = %s",
            (article_id,),
        )
    except Exception:
        pass


def mark_reprocess_requested(article_id: int) -> str:
    """Stamp reprocess_requested_at (audit marker: "a fresh analysis was
    explicitly requested at X") and flip analysis_status to processing.
    Returns the timestamp used, even if the write itself silently no-ops
    on a pre-migration database missing these columns."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        db.execute(
            "update articles set reprocess_requested_at = %s, analysis_status = 'processing' where id = %s",
            (now, article_id),
        )
    except Exception:
        pass
    return now


def _mark_failed(article_id: int, error: str) -> None:
    try:
        db.execute(
            "update articles set analysis_status = 'failed', analysis_error = %s, "
            "analysis_finished_at = %s where id = %s",
            (error[:2000], datetime.now(timezone.utc).isoformat(), article_id),
        )
    except Exception:
        pass


def _primary_project_id_for_article(article_id: int) -> int | None:
    """The single project this article is already linked to, if exactly
    one - used to scope idea-cluster attribution for on-demand reanalysis,
    which (unlike a scrape run) has no single "run for project X" context
    to draw from otherwise. None (no scoping) if the article is linked to
    zero or multiple projects."""
    try:
        rows = db.fetch_all(
            "select distinct project_id from article_projects where article_id = %s",
            (article_id,),
        )
    except Exception:
        return None
    ids = [row.get("project_id") for row in rows or [] if row.get("project_id") is not None]
    return int(ids[0]) if len(ids) == 1 else None


def reanalyze_article(article_id: int) -> dict:
    """Runs synchronously in whatever context calls it - the FastAPI routes
    in main.py invoke this via BackgroundTasks so the request itself
    returns immediately. Always returns a result dict, never raises -
    failures are reported in the dict and persisted to analysis_error."""
    article = load_article_for_reanalysis(article_id)
    if not article:
        return {"article_id": article_id, "ok": False, "analysis_status": "not_found", "analysis_error": "article_not_found"}

    try:
        project_id = _primary_project_id_for_article(article_id)
        result = analyze_article(dict(article), project_context="")
    except Exception as e:
        _mark_failed(article_id, str(e))
        return {"article_id": article_id, "ok": False, "analysis_status": "failed", "analysis_error": str(e)}

    merged = {**article, **result}
    try:
        saved, _ = save_articles([merged], project_id=project_id)
    except Exception as e:
        _mark_failed(article_id, f"save_failed: {e}")
        return {"article_id": article_id, "ok": False, "analysis_status": "failed", "analysis_error": f"save_failed: {e}"}

    return {
        "article_id": article_id,
        "ok": bool(saved) and result.get("analysis_status") == "success",
        "analysis_status": result.get("analysis_status"),
        "analysis_error": result.get("analysis_error"),
    }


def reanalyze_articles(article_ids: list[int]) -> list[dict]:
    return [reanalyze_article(article_id) for article_id in article_ids]
