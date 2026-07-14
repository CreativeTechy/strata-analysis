"""Polling worker that triggers due event reruns on their configured interval.

Interval-based, not cron-based: each event carries repeat_enabled/repeat_interval_value/
repeat_interval_unit/next_run_at, computed by events_store.py after every pipeline run.
This loop just polls for events whose next_run_at has passed and starts the same
pipeline path /scrape uses, reusing pipeline_runs.py for the duplicate-run guard.
"""

import asyncio
import uuid

import config
from events_store import claim_due_event, list_due_events, list_sources_for_event
from pipeline import run_scraper_pipeline
from pipeline_runs import create_pipeline_run, get_active_run_for_event


async def _trigger_due_event(event):
    event_id = event.get("id")
    try:
        # Claim first: only one poll tick may start this event's run, even across restarts.
        if not claim_due_event(event_id):
            return

        if get_active_run_for_event(event_id):
            # Another run is already in flight; the next completion will reschedule us.
            return

        if not list_sources_for_event(event_id):
            return

        run = create_pipeline_run(
            status="queued",
            stage="queued",
            message="Queued by the repeat scheduler.",
            event_id=event_id,
        )
        run_id = run["id"] if run else uuid.uuid4().hex
        await asyncio.to_thread(run_scraper_pipeline, run_id, event_id)
    except Exception as e:
        print(f"Scheduler failed to trigger event {event_id}: {e}")


async def poll_due_events():
    # Spawned as tasks (not awaited inline) so multiple due events run concurrently
    # instead of queuing behind each other's full pipeline duration.
    for event in list_due_events():
        asyncio.create_task(_trigger_due_event(event))


async def scheduler_loop():
    while True:
        try:
            await poll_due_events()
        except Exception as e:
            print(f"Scheduler poll failed: {e}")
        await asyncio.sleep(config.SCHEDULER_POLL_SECONDS)
