"""Shared scrape -> enrich -> save pipeline execution.

Used by both the /scrape endpoint and the interval scheduler so there is a
single place that runs the pipeline and records its outcome.
"""

import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from events_store import list_sources_for_event, record_run_completion
from pipeline_runs import update_pipeline_run

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR.parent / "storage"

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


def _load_pipeline_stats(stats_file: Path):
    if not stats_file.exists():
        return {}
    try:
        return json.loads(stats_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _finish_run(run_id, event_id, **fields):
    """Persist the terminal pipeline_runs state and reschedule the event's next run."""
    update_pipeline_run(run_id, **fields)
    if event_id is not None:
        record_run_completion(event_id, status=fields.get("status"), completed_at=datetime.now(timezone.utc))


def run_scraper_pipeline(run_id: str, event_id: int | None = None):
    """Scrape -> enrich -> save. enrich.py performs the Postgres upsert."""
    if _is_cancel_requested(run_id):
        _finish_run(
            run_id,
            event_id,
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
    if event_id is not None:
        env["PIPELINE_EVENT_ID"] = str(event_id)
    with tempfile.TemporaryDirectory(prefix=f"run-{run_id}-", dir=STORAGE_DIR) as run_dir:
        run_path = Path(run_dir)
        raw_file = run_path / "articles.raw.json"
        enriched_file = run_path / "articles.enriched.json"
        stats_file = run_path / "pipeline.stats.json"
        env["PIPELINE_WORKDIR"] = str(run_path)
        env["PIPELINE_RAW_FILE"] = str(raw_file)
        env["PIPELINE_ENRICHED_FILE"] = str(enriched_file)
        env["PIPELINE_STATS_FILE"] = str(stats_file)

        if event_id is not None:
            try:
                sources = list_sources_for_event(event_id)
                source_urls = [source.get("url") for source in sources if source.get("url")]
                if source_urls:
                    env["SOURCES"] = ",".join(source_urls)
                else:
                    _finish_run(
                        run_id,
                        event_id,
                        status="failed",
                        stage="error",
                        message="Selected event has no sources assigned.",
                        error="No sources assigned to the selected event.",
                        finished_at=datetime.now(timezone.utc).isoformat(),
                    )
                    return
            except Exception:
                pass

        try:
            update_pipeline_run(
                run_id,
                status="running",
                stage="scrape",
                message="Starting scrape...",
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            print("1. Scraping configured sources...")
            _run_step(run_id, ["scrapy", "crawl", "source_rss", "-O", str(raw_file)], BASE_DIR, env)

            update_pipeline_run(run_id, stage="enrich", message="Scrape complete. Enriching articles...")
            print("2. Enriching + saving...")
            _run_step(run_id, [sys.executable, "enrich.py"], BASE_DIR, env)

            if _is_cancel_requested(run_id):
                raise PipelineCancelled()

            stats = _load_pipeline_stats(stats_file)
            _finish_run(
                run_id,
                event_id,
                status="success",
                stage="done",
                message="Pipeline complete.",
                articles_scraped=int(stats.get("articles_scraped") or 0),
                articles_cleaned=int(stats.get("articles_cleaned") or 0),
                articles_saved=int(stats.get("articles_saved") or 0),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            print("Pipeline complete!")
        except PipelineCancelled:
            _finish_run(
                run_id,
                event_id,
                status="cancelled",
                stage="cancelled",
                message="Pipeline cancelled by user.",
                cancelled_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            print(f"Pipeline {run_id} cancelled.")
        except subprocess.CalledProcessError as e:
            _finish_run(
                run_id,
                event_id,
                status="failed",
                stage="error",
                message="Pipeline failed.",
                error=str(e),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            print(f"Pipeline failed: {e}")
        except Exception as e:
            _finish_run(
                run_id,
                event_id,
                status="failed",
                stage="error",
                message="Pipeline crashed.",
                error=str(e),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            print(f"Pipeline crashed: {e}")
        finally:
            _clear_cancellation(run_id)
