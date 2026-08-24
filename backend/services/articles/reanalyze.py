"""On-demand (re)analysis for a single stored article.

This is the "run the analysis pipeline on this article again" primitive.
Two callers sit on top of it: the FastAPI layer (main.py, the project
document endpoints) queues it via BackgroundTasks for one-off retries, and
services/pipeline/pipeline.py drives it in bulk as a tracked analysis run.
It always runs in-process - a single article is seconds of model calls, not
work that needs its own process.
"""

from __future__ import annotations

from datetime import datetime, timezone

import db
from analysis.orchestrator import analyze_article
from services.articles.store import save_articles

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


def reanalyze_article(article_id: int, run_id: str | None = None) -> dict:
    """Runs synchronously in whatever context calls it - the FastAPI routes
    in main.py invoke this via BackgroundTasks so the request itself
    returns immediately. Always returns a result dict, never raises -
    failures are reported in the dict and persisted to analysis_error.

    `run_id`, when this is part of a tracked analysis run, tags the article
    with that run so per-run dashboard/report scoping works. save_articles
    only fills it in where it is still null, so an article keeps the run that
    first analyzed it rather than being re-attributed on every retry."""
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
        saved, _ = save_articles([merged], project_id=project_id, run_id=run_id)
    except Exception as e:
        _mark_failed(article_id, f"save_failed: {e}")
        return {"article_id": article_id, "ok": False, "analysis_status": "failed", "analysis_error": f"save_failed: {e}"}

    return {
        "article_id": article_id,
        "ok": bool(saved) and result.get("analysis_status") == "success",
        "analysis_status": result.get("analysis_status"),
        "analysis_error": result.get("analysis_error"),
    }


def reanalyze_articles(article_ids: list[int], run_id: str | None = None) -> list[dict]:
    return [reanalyze_article(article_id, run_id=run_id) for article_id in article_ids]
