"""Polling worker that triggers due project reruns on their configured interval.

Interval-based, not cron-based: each project carries repeat_enabled/repeat_interval_value/
repeat_interval_unit/next_run_at, computed by projects_store.py after every pipeline run.
This loop just polls for projects whose next_run_at has passed and starts the same
pipeline path /scrape uses, reusing pipeline_runs.py for the duplicate-run guard.
"""

import asyncio
import uuid

import config
from projects_store import claim_due_project, list_due_projects, list_sources_for_project
from pipeline import run_scraper_pipeline
from pipeline_runs import create_pipeline_run, get_active_run_for_project


async def _trigger_due_project(project):
    project_id = project.get("id")
    try:
        # Claim first: only one poll tick may start this project's run, even across restarts.
        if not claim_due_project(project_id):
            return

        if get_active_run_for_project(project_id):
            # Another run is already in flight; the next completion will reschedule us.
            return

        if not list_sources_for_project(project_id):
            return

        run = create_pipeline_run(
            status="queued",
            stage="queued",
            message="Queued by the repeat scheduler.",
            project_id=project_id,
        )
        run_id = run["id"] if run else uuid.uuid4().hex
        await asyncio.to_thread(run_scraper_pipeline, run_id, project_id)
    except Exception as e:
        print(f"Scheduler failed to trigger project {project_id}: {e}")


async def poll_due_projects():
    # Spawned as tasks (not awaited inline) so multiple due projects run concurrently
    # instead of queuing behind each other's full pipeline duration.
    for project in list_due_projects():
        asyncio.create_task(_trigger_due_project(project))


async def scheduler_loop():
    while True:
        try:
            await poll_due_projects()
        except Exception as e:
            print(f"Scheduler poll failed: {e}")
        await asyncio.sleep(config.SCHEDULER_POLL_SECONDS)
