"""Shared scrape -> enrich -> save pipeline execution.

Used by both the /scrape endpoint and the interval scheduler so there is a
single place that runs the pipeline and records its outcome.
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from events_store import list_sources_for_event, record_run_completion
from pipeline_runs import update_pipeline_run

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR.parent / "storage"


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
            subprocess.run(
                ["scrapy", "crawl", "source_rss", "-O", str(raw_file)],
                cwd=BASE_DIR,
                check=True,
                env=env,
            )
            update_pipeline_run(run_id, stage="enrich", message="Scrape complete. Enriching articles...")
            print("2. Enriching + saving...")
            subprocess.run([sys.executable, "enrich.py"], cwd=BASE_DIR, check=True, env=env)
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
