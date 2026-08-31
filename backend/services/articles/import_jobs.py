"""Background JSONL import: batched upserts with live progress.

Importing is the mirror of the streaming export, and has the same reason to be
incremental - a project's export carries every article's full text and
embedding, so a restore reads a file far too large to hold in memory or to
finish inside one request. The upload is spooled to a temp file by the route,
then this job walks it line by line, upserting in batches of BATCH_SIZE through
the same save_articles() the pipeline's saver stage uses. Imported articles
therefore get the identical project link, story grouping and idea-cluster
treatment a scraped one does.

Progress is reported the way competitor discovery/analysis report theirs (see
job_runs.JobRegistry): a process-local run the UI polls, carrying counters and
an append-only log. Nothing here is worth resuming after a restart - the upsert
is keyed on url, so a failed import is simply re-run.
"""

from __future__ import annotations

import json
import os
import time

from services.articles.store import ARTICLE_MUTABLE_FIELDS, save_articles
from services.competitors.job_runs import JobRegistry
from services.pipeline.pipeline import start_or_reuse_analysis_run

# Rows per upsert batch. Deliberately smaller than the export's page size: each
# saved article also writes its project link, story group and idea clusters, so
# a batch is a lot more work than a page of reads.
BATCH_SIZE = 200

# Unusable lines are counted in full but only the first few are handed back -
# a file with the wrong shape would otherwise report one error per line.
MAX_ERRORS_REPORTED = 50

# Progress is logged on a timer rather than per batch, so the log stays
# readable whether the file holds 900 articles or 900,000. The interval also
# stretches with the run (never below this floor) so that a long import ends up
# with tens of log lines rather than one per two seconds for an hour - the
# whole log ships with every status poll.
LOG_INTERVAL_SECONDS = 2.0
TARGET_LOG_LINES = 30

_import_runs = JobRegistry("Queued for import.")


def create_import_run(project_id: int | None = None, filename: str = "", total_lines: int = 0) -> str:
    """Register a queued import. `total_lines` is the route's newline count for
    the uploaded file - an estimate of the record count used for percentage and
    ETA only, never for control flow."""
    return _import_runs.create(
        project_id,
        filename=filename or "articles.jsonl",
        total_lines=int(total_lines or 0),
        processed=0,
        received=0,
        saved=0,
        skipped=0,
        elapsed_seconds=0.0,
        rate_per_second=0.0,
        by_source={},
        errors=[],
    )


def get_import_run(run_id: str) -> dict | None:
    return _import_runs.get(run_id)


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _progress_message(saved: int, total_lines: int, rate: float, elapsed: float, processed: int) -> str:
    scope = f"{saved:,} of ~{total_lines:,}" if total_lines else f"{saved:,}"
    parts = [f"Imported {scope} articles", f"{rate:,.0f}/s"]
    if total_lines and rate > 0 and processed < total_lines:
        parts.append(f"~{_format_duration((total_lines - processed) / rate)} left")
    else:
        parts.append(f"{_format_duration(elapsed)} elapsed")
    return f"{parts[0]} - {', '.join(parts[1:])}"


def run_import_job(run_id: str, path: str, project_id: int | None = None) -> None:
    """Import the spooled JSONL at `path`, then delete it.

    Runs as a FastAPI BackgroundTask (sync, so in the threadpool). Never raises:
    a failure is recorded on the run, which is what the UI is polling.
    """
    started = time.monotonic()
    allowed = set(ARTICLE_MUTABLE_FIELDS)
    run = _import_runs.get(run_id) or {}
    total_lines = int(run.get("total_lines") or 0)

    errors: list[dict] = []
    saved_by_source: dict[str, int] = {}
    batch: list[dict] = []
    processed = 0
    received = 0
    saved = 0
    skipped = 0
    last_log = started

    def elapsed() -> float:
        return max(time.monotonic() - started, 1e-6)

    def rate() -> float:
        return processed / elapsed()

    def publish(**fields) -> None:
        _import_runs.update(
            run_id,
            processed=processed,
            received=received,
            saved=saved,
            skipped=skipped,
            elapsed_seconds=round(elapsed(), 2),
            rate_per_second=round(rate(), 1),
            by_source=dict(saved_by_source),
            errors=list(errors),
            **fields,
        )

    def note_error(line_number: int, message: str) -> None:
        nonlocal skipped
        skipped += 1
        if len(errors) < MAX_ERRORS_REPORTED:
            errors.append({"line": line_number, "error": message})

    def flush() -> None:
        nonlocal saved, batch
        if not batch:
            return
        count, by_source = save_articles(batch, project_id=project_id)
        saved += count
        for key, value in (by_source or {}).items():
            saved_by_source[key] = saved_by_source.get(key, 0) + int(value)
        batch = []

    _import_runs.update(run_id, status="running", stage="importing", message="Reading the file...")
    _import_runs.append_log(
        run_id,
        f"Importing {run.get('filename') or 'articles.jsonl'}"
        + (f" (~{total_lines:,} lines)." if total_lines else "."),
    )

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for lineno, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                processed += 1

                # First line with anything on it, not literally line 1 - a
                # leading blank line shouldn't hide a whole-file JSON array.
                if processed == 1 and line.startswith("["):
                    raise ValueError("Expected JSON Lines (one article object per line), not a JSON array.")

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    note_error(lineno, f"Invalid JSON: {exc.msg}")
                    continue
                if not isinstance(entry, dict):
                    note_error(lineno, "Expected a JSON object.")
                    continue
                url = str(entry.get("url") or "").strip()
                if not url:
                    note_error(lineno, "Missing url.")
                    continue

                row = {key: value for key, value in entry.items() if key in allowed}
                row["url"] = url
                received += 1
                batch.append(row)

                if len(batch) >= BATCH_SIZE:
                    flush()
                    now = time.monotonic()
                    if now - last_log >= max(LOG_INTERVAL_SECONDS, elapsed() / TARGET_LOG_LINES):
                        last_log = now
                        message = _progress_message(saved, total_lines, rate(), elapsed(), processed)
                        _import_runs.append_log(run_id, message)
                        publish(message=message)
                    else:
                        publish()
        flush()
    except Exception as exc:
        publish()
        _import_runs.append_log(run_id, f"Import failed: {exc}")
        _import_runs.update(
            run_id,
            status="failed",
            stage="failed",
            message=str(exc),
            error=str(exc),
        )
        return
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    if received == 0:
        detail = errors[0]["error"] if errors else "No articles found in the file."
        publish()
        _import_runs.append_log(run_id, f"Nothing to import. {detail}")
        _import_runs.update(run_id, status="failed", stage="failed", message=f"Nothing to import. {detail}", error=detail)
        return

    summary = (
        f"Imported {saved:,} article{'' if saved == 1 else 's'} in {_format_duration(elapsed())} "
        f"({rate():,.0f}/s)."
    )
    if skipped:
        summary += f" Skipped {skipped:,} unusable line{'' if skipped == 1 else 's'}."

    # 'all' (unlinked) imports have no project to run analysis against - only
    # a project-scoped import can start one.
    analysis_run_id = None
    if project_id is not None and saved > 0:
        run_info = start_or_reuse_analysis_run(project_id)
        analysis_run_id = run_info["run_id"]
        summary += " Starting analysis." if run_info["started"] else " Joining the active analysis run."

    _import_runs.append_log(run_id, summary)
    publish(status="success", stage="done", message=summary, analysis_run_id=analysis_run_id)
