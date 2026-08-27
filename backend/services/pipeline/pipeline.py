"""Shared analysis pipeline execution.

One run = re-run the AI stage pipeline (backend/analysis/orchestrator.py) over
every article a project holds that is in scope, recording progress into
`pipeline_runs` as it goes so the dashboard can watch it live.

Why this is a thread and not a subprocess
-----------------------------------------
The crawler this product was forked from ran `scrapy crawl` as a child process,
so stopping a run meant killing a process tree. There is no external process
here: analysis is a sequence of in-process model/LLM calls, so a run is a
worker thread and cancellation is a flag checked between articles. That also
means a stop lands within one article rather than instantly - accepted, since
an article is seconds of work, not a whole crawl.

Articles are analyzed through a small thread pool (ANALYSIS_CONCURRENCY,
default 2) rather than serially: with `LLM_PROVIDER=ollama` the ceiling is the
local model host, not an API quota, and one in-flight request usually leaves
the machine idle between tokens. Keep it low - every worker competes for the
same local GPU/CPU as the embedding model.

A run also stops early - the same way a user-requested cancellation does -
when an article's analysis raises one of FATAL_ANALYSIS_ERRORS (see
services/articles/analysis_defaults.py): reanalyze_article() flags that
result `fatal`, and _analyze() below turns it into a PipelineFatalError so
the rest of `rows` is never handed to doomed calls against an unusable
provider.
"""

import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import config
import db
from services.articles.reanalyze import mark_processing, reanalyze_article
from services.pipeline.pipeline_runs import (
    update_pipeline_run,
    upsert_pipeline_run_document_stats,
)
from services.projects.projects_store import record_run_completion

# Articles whose analysis has not succeeded yet - the default scope, so a
# re-run after a provider outage picks up exactly what the outage cost and
# doesn't spend the model's time re-deriving answers that already landed.
PENDING_STATUSES = ("pending", "processing", "failed")

# Label for articles that belong to the project but came from somewhere other
# than an uploaded document (a JSONL import, most often).
UNATTRIBUTED = "Imported articles"

# Runs that have been asked to cancel. Checked before each article is handed to
# the pool and again inside the worker, so a stop lands at the next article
# boundary rather than mid-analysis.
_cancel_requested = set()
_registry_lock = threading.Lock()


class PipelineCancelled(Exception):
    """Raised internally when a run is stopped by the user."""


class PipelineFatalError(Exception):
    """Raised internally when an article's analysis fails with one of
    FATAL_ANALYSIS_ERRORS (see services/articles/analysis_defaults.py) - the
    provider itself is unusable, so every remaining article would fail the
    exact same way. Stops the run the same way PipelineCancelled does,
    instead of grinding through the rest as doomed per-article calls."""


def _is_cancel_requested(run_id):
    with _registry_lock:
        return run_id in _cancel_requested


def _clear_cancellation(run_id):
    with _registry_lock:
        _cancel_requested.discard(run_id)


def cancel_pipeline_run(run_id: str) -> bool:
    """Request cancellation of a run.

    Always returns True: unlike the scrape pipeline this replaces, there is no
    child process to find and kill - the run's own worker sees the flag at its
    next article boundary. A stop for a run that already finished is harmless
    (the flag is cleared when a run ends).
    """
    with _registry_lock:
        _cancel_requested.add(run_id)
    return True


def _now():
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Selecting the work
# --------------------------------------------------------------------------- #
def _select_articles(project_id, scope):
    """Every in-scope article for the project, with the document it came from.

    Left-joined through project_document_articles: an article that was imported
    rather than split out of a document simply has no document row, and lands
    under UNATTRIBUTED in the per-document breakdown.
    """
    status_filter = ""
    params = [int(project_id)]
    if scope != "all":
        status_filter = "and coalesce(a.analysis_status, 'pending') = any(%s)"
        params.append(list(PENDING_STATUSES))

    rows = db.fetch_all(
        f"""
        select distinct on (a.id)
               a.id,
               pd.id as document_id,
               pd.original_filename as document
        from articles a
        inner join article_projects ap on ap.article_id = a.id
        left join project_document_articles pda
               on pda.article_id = a.id and pda.project_id = ap.project_id
        left join project_documents pd on pd.id = pda.document_id
        where ap.project_id = %s
          {status_filter}
        order by a.id asc
        """,
        tuple(params),
    )
    return rows or []


def _initial_document_stats(rows):
    stats = {}
    for row in rows:
        label = (row.get("document") or UNATTRIBUTED).strip() or UNATTRIBUTED
        entry = stats.setdefault(
            label,
            {"document_id": row.get("document_id"), "selected": 0, "analyzed": 0, "failed": 0, "note": ""},
        )
        entry["selected"] += 1
    return stats


# --------------------------------------------------------------------------- #
# Running it
# --------------------------------------------------------------------------- #
def _finish_run(run_id, project_id, **fields):
    """Persist the terminal pipeline_runs state and stamp the project's last run."""
    update_pipeline_run(run_id, **fields)
    if project_id is not None:
        record_run_completion(project_id, status=fields.get("status"), completed_at=datetime.now(timezone.utc))


def run_analysis_pipeline(run_id: str, project_id: int | None = None, scope: str = "pending"):
    """Analyze this project's articles, recording progress into `pipeline_runs`.

    `scope` is "pending" (only articles whose analysis hasn't succeeded) or
    "all" (re-analyze everything the project holds).
    """
    if _is_cancel_requested(run_id):
        _finish_run(
            run_id,
            project_id,
            status="cancelled",
            stage="cancelled",
            message="Analysis cancelled before it started.",
            cancelled_at=_now(),
            finished_at=_now(),
        )
        _clear_cancellation(run_id)
        return

    if project_id is None:
        _finish_run(
            run_id,
            project_id,
            status="failed",
            stage="error",
            message="No project selected for this analysis run.",
            error="project_id is required.",
            finished_at=_now(),
        )
        _clear_cancellation(run_id)
        return

    started = _now()
    try:
        update_pipeline_run(
            run_id,
            status="running",
            stage="prepare",
            message="Selecting articles to analyze...",
            started_at=started,
            prepare_started_at=started,
        )

        rows = _select_articles(project_id, scope)
        document_stats = _initial_document_stats(rows)
        upsert_pipeline_run_document_stats(run_id, document_stats)
        update_pipeline_run(
            run_id,
            articles_selected=len(rows),
            prepare_finished_at=_now(),
        )

        if not rows:
            _finish_run(
                run_id,
                project_id,
                status="success",
                stage="done",
                message=(
                    "Nothing to analyze - every article in this project has already been analyzed."
                    if scope != "all"
                    else "Nothing to analyze - this project has no articles yet."
                ),
                finished_at=_now(),
            )
            return

        if _is_cancel_requested(run_id):
            raise PipelineCancelled()

        analysis_started = _now()
        update_pipeline_run(
            run_id,
            stage="analyze",
            message=f"Analyzing {len(rows)} article(s)...",
            analysis_started_at=analysis_started,
        )

        counters = {"analyzed": 0, "failed": 0}
        counters_lock = threading.Lock()

        def _analyze(row):
            if _is_cancel_requested(run_id):
                raise PipelineCancelled()
            article_id = int(row["id"])
            label = (row.get("document") or UNATTRIBUTED).strip() or UNATTRIBUTED
            mark_processing(article_id)
            result = reanalyze_article(article_id, run_id=run_id)
            ok = bool(result.get("ok"))

            with counters_lock:
                counters["analyzed" if ok else "failed"] += 1
                entry = document_stats.setdefault(
                    label,
                    {"document_id": row.get("document_id"), "selected": 0, "analyzed": 0, "failed": 0, "note": ""},
                )
                entry["analyzed" if ok else "failed"] += 1
                if not ok and result.get("analysis_error"):
                    entry["note"] = str(result["analysis_error"])[:500]
                snapshot = dict(counters)
                document_snapshot = {label: dict(entry)}

            # Written per article rather than once at the end so the dashboard's
            # progress bar and per-document breakdown fill in while the run is
            # still going, the way the crawler's per-source rows used to.
            update_pipeline_run(
                run_id,
                articles_analyzed=snapshot["analyzed"],
                articles_failed=snapshot["failed"],
                message=f"Analyzed {snapshot['analyzed'] + snapshot['failed']} of {len(rows)} article(s)...",
            )
            upsert_pipeline_run_document_stats(run_id, document_snapshot)

            if result.get("fatal"):
                raise PipelineFatalError(str(result.get("analysis_error") or "The AI provider is unreachable."))

        workers = max(1, int(config.ANALYSIS_CONCURRENCY))
        if workers == 1:
            for row in rows:
                _analyze(row)
        else:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="analysis") as pool:
                # map() re-raises the first worker exception here, which is how
                # a cancellation mid-run reaches the handler below.
                list(pool.map(_analyze, rows))

        if _is_cancel_requested(run_id):
            raise PipelineCancelled()

        upsert_pipeline_run_document_stats(run_id, document_stats)
        failed = counters["failed"]
        analyzed = counters["analyzed"]
        message = f"Analysis complete: {analyzed} analyzed"
        if failed:
            message += f", {failed} failed"
        _finish_run(
            run_id,
            project_id,
            # A run that analyzed nothing successfully while every article
            # failed is a failed run, not a run with a footnote - that is what
            # a misconfigured or unreachable local model looks like from here.
            status="failed" if failed and not analyzed else "success",
            stage="error" if failed and not analyzed else "done",
            message=message + ".",
            error="Every article failed to analyze." if failed and not analyzed else None,
            articles_analyzed=analyzed,
            articles_failed=failed,
            analysis_finished_at=_now(),
            finished_at=_now(),
        )
        print(f"[analysis] run {run_id}: {message}.")
    except PipelineCancelled:
        _finish_run(
            run_id,
            project_id,
            status="cancelled",
            stage="cancelled",
            message="Analysis cancelled by user.",
            cancelled_at=_now(),
            finished_at=_now(),
        )
        print(f"Analysis run {run_id} cancelled.")
    except PipelineFatalError as exc:
        _finish_run(
            run_id,
            project_id,
            status="failed",
            stage="error",
            message=f"Analysis stopped: {exc}",
            error=str(exc),
            articles_analyzed=counters["analyzed"],
            articles_failed=counters["failed"],
            analysis_finished_at=_now(),
            finished_at=_now(),
        )
        print(f"Analysis run {run_id} stopped: provider unusable ({exc}).")
    except Exception as exc:  # noqa: BLE001 - terminal state must carry the reason
        print(f"Analysis run crashed: {exc}")
        traceback.print_exc()
        _finish_run(
            run_id,
            project_id,
            status="failed",
            stage="error",
            message="Analysis run crashed.",
            error=f"{exc}\n{traceback.format_exc()}",
            finished_at=_now(),
        )
    finally:
        _clear_cancellation(run_id)
