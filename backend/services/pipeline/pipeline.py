"""Shared scrape -> enrich -> save pipeline execution.

Used by both the /scrape endpoint and the interval scheduler so there is a
single place that runs the pipeline and records its outcome.

A single `scrapy crawl` subprocess does the whole run - scraping, cleaning,
enriching, and saving each article as it's scraped (see
scraper/pipelines.py's StreamingEnrichPipeline), rather than the previous
two-subprocess design (a full `scrapy crawl -O raw_file` followed by a
separate `python -m services.articles.enrich` pass over the whole file).
That's what lets the dashboard's per-source breakdown fill in source by
source while the crawl is still running, instead of only appearing once the
slowest source in the run finishes.
"""

import os
import platform
import subprocess
import tempfile
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path

from services.projects.projects_store import list_sources_for_project, record_run_completion
from services.pipeline.pipeline_runs import (
    get_pipeline_run,
    get_pipeline_run_sources,
    update_pipeline_run,
    upsert_pipeline_run_source_stats,
)
from services.pipeline.source_diagnostics import build_fetch_note, load_source_diagnostics, summarize_notable_diagnostics

# services/pipeline/pipeline.py -> services/pipeline -> services -> backend/.
# BASE_DIR must be the backend root (not this file's own directory): it's
# used as the cwd for both the `scrapy crawl` subprocess (needs scrapy.cfg,
# which lives at backend root) and the enrich-stage subprocess below.
BASE_DIR = Path(__file__).resolve().parents[2]
STORAGE_DIR = BASE_DIR.parent / "storage"
RUNS_DIR = STORAGE_DIR / "runs"

IS_WINDOWS = platform.system() == "Windows"

# Tracks the live Popen for each run so a stop request can reach the actual
# OS process, plus which run_ids have been asked to cancel (checked between
# pipeline stages so a stop between scrape/enrich still lands on "cancelled").
_active_processes = {}
_cancel_requested = set()
_registry_lock = threading.Lock()


class PipelineCancelled(Exception):
    """Raised internally when a run is stopped by the user."""


def _register_process(run_id, proc):
    with _registry_lock:
        _active_processes[run_id] = proc


def _unregister_process(run_id):
    with _registry_lock:
        _active_processes.pop(run_id, None)


def _is_cancel_requested(run_id):
    with _registry_lock:
        return run_id in _cancel_requested


def _clear_cancellation(run_id):
    with _registry_lock:
        _cancel_requested.discard(run_id)
        _active_processes.pop(run_id, None)


def _kill_process_tree(proc):
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            import signal

            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        pass


def cancel_pipeline_run(run_id: str) -> bool:
    """Request cancellation of a run and kill its live process tree, if any.

    Returns True if a live process was found and terminated. Either way the
    run_id is marked so the pipeline thread bails out at its next checkpoint
    (e.g. if the stop arrives while queued or between stages).
    """
    with _registry_lock:
        _cancel_requested.add(run_id)
        proc = _active_processes.get(run_id)
    if proc is not None:
        _kill_process_tree(proc)
        return True
    return False


def _popen(cmd, cwd, env):
    kwargs = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, cwd=cwd, env=env, **kwargs)


def _run_step(run_id, cmd, cwd, env):
    """Run one pipeline stage as a trackable subprocess.

    Raises PipelineCancelled if the run was stopped before or during the
    stage, or subprocess.CalledProcessError if it failed on its own.
    """
    if _is_cancel_requested(run_id):
        raise PipelineCancelled()

    proc = _popen(cmd, cwd, env)
    _register_process(run_id, proc)
    try:
        returncode = proc.wait()
    finally:
        _unregister_process(run_id)

    if _is_cancel_requested(run_id):
        raise PipelineCancelled()
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd)


def _merge_fetch_diagnostics(run_id, workdir):
    """Fold the spider's end-of-run fetch diagnostics (source_diagnostics.json
    - only ever writable once the whole crawl closes, so this can't be
    streamed per-item like the rest of a source's stats) into whatever
    pipeline_run_sources rows StreamingEnrichPipeline already wrote live
    during the run. Also adds a row for a source that produced zero items at
    all (e.g. fully blocked) and therefore never got a row from the pipeline.
    Returns the diagnostics list too, for the caller's own console logging.
    """
    diagnostics = load_source_diagnostics(workdir)
    diagnostics_by_source = {
        entry.get("source_name"): entry for entry in diagnostics if entry.get("source_name")
    }
    existing_rows = {row["source"]: row for row in get_pipeline_run_sources(run_id)}

    merged = {}
    for source in set(diagnostics_by_source) | set(existing_rows):
        row = existing_rows.get(source) or {}
        diagnostic = diagnostics_by_source.get(source)
        scraped_count = int(row.get("scraped") or 0)
        merged[source] = {
            "source_url": (diagnostic or {}).get("source_url") or row.get("source_url"),
            "scraped": scraped_count,
            "duplicate": row.get("duplicate", 0),
            "blocked": row.get("blocked", 0),
            "date_filtered": row.get("date_filtered", 0),
            "skipped_existing": row.get("skipped_existing", 0),
            "kept": row.get("kept", 0),
            "enriched": row.get("enriched", 0),
            "saved": row.get("saved", 0),
            "http_status": (diagnostic or {}).get("http_status"),
            "network_blocked": bool((diagnostic or {}).get("network_blocked")),
            "fetch_note": build_fetch_note(diagnostic, scraped_count),
        }
    if merged:
        upsert_pipeline_run_source_stats(run_id, merged)
    return diagnostics


def _finish_run(run_id, project_id, **fields):
    """Persist the terminal pipeline_runs state and reschedule the project's next run."""
    update_pipeline_run(run_id, **fields)
    if project_id is not None:
        record_run_completion(project_id, status=fields.get("status"), completed_at=datetime.now(timezone.utc))


def run_scraper_pipeline(run_id: str, project_id: int | None = None):
    """Scrape, clean, enrich, and save - all within one `scrapy crawl`
    subprocess (see scraper/pipelines.py's StreamingEnrichPipeline)."""
    if _is_cancel_requested(run_id):
        _finish_run(
            run_id,
            project_id,
            status="cancelled",
            stage="cancelled",
            message="Pipeline cancelled before it started.",
            cancelled_at=datetime.now(timezone.utc).isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        _clear_cancellation(run_id)
        return

    env = os.environ.copy()
    env["PIPELINE_RUN_ID"] = run_id
    if project_id is not None:
        env["PIPELINE_PROJECT_ID"] = str(project_id)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"run-{run_id}-", dir=RUNS_DIR) as run_dir:
        run_path = Path(run_dir)
        # Debug artifact only now - StreamingEnrichPipeline processes each
        # item as it's scraped, so nothing reads this file back afterward the
        # way enrich.py used to.
        raw_file = run_path / "articles.raw.json"
        env["PIPELINE_WORKDIR"] = str(run_path)

        if project_id is not None:
            try:
                sources = list_sources_for_project(project_id)
                if not any(source.get("url") for source in sources):
                    _finish_run(
                        run_id,
                        project_id,
                        status="failed",
                        stage="error",
                        message="Selected project has no sources assigned.",
                        error="No sources assigned to the selected project.",
                        finished_at=datetime.now(timezone.utc).isoformat(),
                    )
                    return
            except Exception:
                pass

        try:
            scrape_start = datetime.now(timezone.utc).isoformat()
            update_pipeline_run(
                run_id,
                status="running",
                stage="scrape",
                message="Starting scrape and enrichment...",
                started_at=scrape_start,
                scrape_started_at=scrape_start,
            )
            print("Scraping, cleaning, enriching, and saving sources...")
            _run_step(run_id, ["scrapy", "crawl", "source_rss", "-O", str(raw_file)], BASE_DIR, env)

            if _is_cancel_requested(run_id):
                raise PipelineCancelled()

            scrape_finished = datetime.now(timezone.utc).isoformat()
            update_pipeline_run(run_id, scrape_finished_at=scrape_finished)

            # Fetch-level diagnostics (was a source blocked/404/DNS-failed)
            # are only ever knowable once the whole crawl closes - this folds
            # them into the pipeline_run_sources rows StreamingEnrichPipeline
            # already wrote live during the run (see _merge_fetch_diagnostics).
            diagnostics = _merge_fetch_diagnostics(run_id, str(run_path))
            # Debug visibility: print every source that had a fetch problem
            # (403/blocked/etc.) straight to the backend console, with the
            # full detail captured in source_rss.py - the run's own
            # status/message stay "success" here (a blocked source doesn't
            # fail the whole run), so without this the real cause is only
            # visible by opening the run's per-source breakdown afterward.
            for entry in diagnostics:
                if entry.get("http_status") or entry.get("note"):
                    print(
                        f"[pipeline] source diagnostic: {entry.get('source_name')!r} "
                        f"-> HTTP {entry.get('http_status')} blocked={entry.get('network_blocked')} "
                        f"note={entry.get('note')}"
                    )
            diagnostics_summary = summarize_notable_diagnostics(diagnostics)
            completion_message = "Pipeline complete." + (f" {diagnostics_summary}" if diagnostics_summary else "")

            # articles_scraped/cleaned/saved were already kept live-updated
            # throughout the run (by the spider itself and by
            # StreamingEnrichPipeline respectively) - read the current row
            # back rather than a stats file no longer written anywhere.
            final_run = get_pipeline_run(run_id) or {}
            _finish_run(
                run_id,
                project_id,
                status="success",
                stage="done",
                message=completion_message,
                articles_scraped=int(final_run.get("articles_scraped") or 0),
                articles_cleaned=int(final_run.get("articles_cleaned") or 0),
                articles_saved=int(final_run.get("articles_saved") or 0),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            print("Pipeline complete!")
        except PipelineCancelled:
            _finish_run(
                run_id,
                project_id,
                status="cancelled",
                stage="cancelled",
                message="Pipeline cancelled by user.",
                cancelled_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            print(f"Pipeline {run_id} cancelled.")
        except subprocess.CalledProcessError as e:
            # str(e) alone is just "Command '...' returned non-zero exit
            # status N." - no hint of *why* (a 403 alone won't trigger this,
            # since scrapy still exits 0 on a blocked source; this fires for
            # a harder failure such as a spider crash) - print cmd/returncode
            # plus whatever fetch diagnostics did get written before the
            # crash, so the real cause is visible in the backend console.
            # StreamingEnrichPipeline's per-source rows already reflect
            # whatever it got through before the crash - still worth folding
            # in fetch diagnostics for whatever they cover.
            diagnostics = _merge_fetch_diagnostics(run_id, str(run_path))
            for entry in diagnostics:
                if entry.get("http_status") or entry.get("note"):
                    print(
                        f"[pipeline] source diagnostic (at failure): {entry.get('source_name')!r} "
                        f"-> HTTP {entry.get('http_status')} blocked={entry.get('network_blocked')} "
                        f"note={entry.get('note')}"
                    )
            print(f"Pipeline failed: cmd={e.cmd} returncode={e.returncode}")
            _finish_run(
                run_id,
                project_id,
                status="failed",
                stage="error",
                message="Pipeline failed.",
                error=str(e),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            print(f"Pipeline crashed: {e}")
            traceback.print_exc()
            _finish_run(
                run_id,
                project_id,
                status="failed",
                stage="error",
                message="Pipeline crashed.",
                error=f"{e}\n{traceback.format_exc()}",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        finally:
            _clear_cancellation(run_id)
