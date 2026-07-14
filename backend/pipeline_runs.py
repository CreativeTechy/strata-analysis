"""Postgres-backed pipeline run tracking helpers."""

import uuid

import config
import db


RUN_SELECT = "id,pipeline,event_id,status,stage,message,articles_scraped,articles_cleaned,articles_saved,crawl_pages,error,started_at,finished_at,cancel_requested_at,cancelled_at,created_at,updated_at"

# Runs in these statuses are still in flight; anything else (success, failed,
# cancelled) is terminal and must not block a new run for the same event.
ACTIVE_STATUSES = ("queued", "running")


def _normalize(row):
    return {
        "id": row.get("id"),
        "pipeline": row.get("pipeline") or "scrape",
        "event_id": row.get("event_id"),
        "status": row.get("status") or "queued",
        "stage": row.get("stage") or "queued",
        "message": row.get("message") or "",
        "articles_scraped": row.get("articles_scraped") or 0,
        "articles_cleaned": row.get("articles_cleaned") or 0,
        "articles_saved": row.get("articles_saved") or 0,
        "crawl_pages": row.get("crawl_pages") or 0,
        "error": row.get("error") or "",
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "cancel_requested_at": row.get("cancel_requested_at"),
        "cancelled_at": row.get("cancelled_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _fetch_by_id(run_id):
    row = db.fetch_one(f"select {RUN_SELECT} from pipeline_runs where id = %s limit 1", (run_id,))
    return _normalize(row) if row else None


def get_pipeline_run(run_id):
    if not config.DATABASE_URL or not run_id:
        return None
    try:
        return _fetch_by_id(run_id)
    except Exception:
        return None


def get_active_run_for_event(event_id):
    """Return the in-flight run for this event, or None if it's free to start.

    A run is "active" if it's queued/running (cancelled/success/failed are all
    terminal) and started recently enough to trust; this keeps a crashed backend
    from permanently blocking future runs for the event.
    """
    if not config.DATABASE_URL or event_id is None:
        return None

    try:
        row = db.fetch_one(
            f"""
            select {RUN_SELECT}
            from pipeline_runs
            where event_id = %s
              and status = any(%s)
              and created_at > now() - (%s || ' minutes')::interval
            order by created_at desc
            limit 1
            """,
            (int(event_id), list(ACTIVE_STATUSES), config.SCHEDULER_STALE_RUN_MINUTES),
        )
        return _normalize(row) if row else None
    except Exception:
        return None


def list_pipeline_runs(limit=10):
    if not config.DATABASE_URL:
        return []

    try:
        rows = db.fetch_all(
            f"""
            select {RUN_SELECT}
            from pipeline_runs
            order by created_at desc
            limit %s
            """,
            (limit,),
        )
        return [_normalize(row) for row in rows]
    except Exception:
        return []


def create_pipeline_run(run_id=None, pipeline="scrape", event_id=None, status="queued", stage="queued", message=""):
    if not config.DATABASE_URL:
        return None

    run_id = run_id or uuid.uuid4().hex
    payload = {
        "id": run_id,
        "pipeline": pipeline,
        "event_id": event_id,
        "status": status,
        "stage": stage,
        "message": message,
    }

    try:
        row = db.fetch_one(
            f"""
            insert into pipeline_runs (id, pipeline, event_id, status, stage, message)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (id) do update set
              pipeline = excluded.pipeline,
              event_id = excluded.event_id,
              status = excluded.status,
              stage = excluded.stage,
              message = excluded.message,
              updated_at = now()
            returning {RUN_SELECT}
            """,
            (
                payload["id"],
                payload["pipeline"],
                payload["event_id"],
                payload["status"],
                payload["stage"],
                payload["message"],
            ),
        )
        return _normalize(row) if row else _fetch_by_id(run_id)
    except Exception:
        return None


def update_pipeline_run(run_id, **fields):
    if not config.DATABASE_URL or not run_id:
        return None

    allowed = {
        "pipeline",
        "event_id",
        "status",
        "stage",
        "message",
        "articles_scraped",
        "articles_cleaned",
        "articles_saved",
        "crawl_pages",
        "error",
        "started_at",
        "finished_at",
        "cancel_requested_at",
        "cancelled_at",
    }
    keys = [key for key in fields.keys() if key in allowed]
    if not keys:
        return _fetch_by_id(run_id)

    assignments = ", ".join(f"{key} = %s" for key in keys)
    params = [fields[key] for key in keys] + [run_id]

    try:
        row = db.fetch_one(
            f"""
            update pipeline_runs
            set {assignments},
                updated_at = now()
            where id = %s
            returning {RUN_SELECT}
            """,
            params,
        )
        return _normalize(row) if row else _fetch_by_id(run_id)
    except Exception:
        return None

