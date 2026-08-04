"""Postgres-backed pipeline run tracking helpers."""

import uuid

import config
import db


RUN_COLUMNS = "id,pipeline,project_id,status,stage,message,articles_scraped,articles_cleaned,articles_saved,crawl_pages,error,started_at,finished_at,cancel_requested_at,cancelled_at,has_detail,scrape_started_at,scrape_finished_at,clean_started_at,clean_finished_at,enrich_started_at,enrich_finished_at,created_at,updated_at"
# INSERT/UPDATE ... RETURNING can only reference the table being written, so those
# statements use RUN_COLUMNS unqualified; anything reading via a join uses RUN_SELECT.
RUN_SELECT = ",".join(f"pr.{column}" for column in RUN_COLUMNS.split(",")) + ",p.name as project_name"

# Runs in these statuses are still in flight; anything else (success, failed,
# cancelled) is terminal and must not block a new run for the same project.
ACTIVE_STATUSES = ("queued", "running")


def _normalize(row):
    return {
        "id": row.get("id"),
        "pipeline": row.get("pipeline") or "scrape",
        "project_id": row.get("project_id"),
        "project_name": row.get("project_name"),
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
        "has_detail": bool(row.get("has_detail")),
        "scrape_started_at": row.get("scrape_started_at"),
        "scrape_finished_at": row.get("scrape_finished_at"),
        "clean_started_at": row.get("clean_started_at"),
        "clean_finished_at": row.get("clean_finished_at"),
        "enrich_started_at": row.get("enrich_started_at"),
        "enrich_finished_at": row.get("enrich_finished_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _normalize_source_stat(row):
    return {
        "source": row.get("source"),
        "source_url": row.get("source_url"),
        "scraped": row.get("scraped") or 0,
        "duplicate": row.get("duplicate") or 0,
        "blocked": row.get("blocked") or 0,
        "date_filtered": row.get("date_filtered") or 0,
        "kept": row.get("kept") or 0,
        "enriched": row.get("enriched") or 0,
        "saved": row.get("saved") or 0,
        # Fetch-time diagnostics (was this source reachable at all this run) -
        # see services/pipeline/source_diagnostics.py. "blocked" above is an
        # unrelated count (articles rejected by content_guard), hence
        # network_blocked rather than reusing that name here.
        "http_status": row.get("http_status"),
        "network_blocked": bool(row.get("network_blocked")),
        "fetch_note": row.get("fetch_note") or "",
    }


def _fetch_by_id(run_id):
    row = db.fetch_one(
        f"select {RUN_SELECT} from pipeline_runs pr left join projects p on p.id = pr.project_id where pr.id = %s limit 1",
        (run_id,),
    )
    return _normalize(row) if row else None


def get_pipeline_run(run_id):
    if not config.DATABASE_URL or not run_id:
        return None
    try:
        return _fetch_by_id(run_id)
    except Exception:
        return None


def get_active_run_for_project(project_id):
    """Return the in-flight run for this project, or None if it's free to start.

    A run is "active" if it's queued/running (cancelled/success/failed are all
    terminal) and started recently enough to trust; this keeps a crashed backend
    from permanently blocking future runs for the project.
    """
    if not config.DATABASE_URL or project_id is None:
        return None

    try:
        row = db.fetch_one(
            f"""
            select {RUN_SELECT}
            from pipeline_runs pr
            left join projects p on p.id = pr.project_id
            where pr.project_id = %s
              and pr.status = any(%s)
              and pr.created_at > now() - (%s || ' minutes')::interval
            order by pr.created_at desc
            limit 1
            """,
            (int(project_id), list(ACTIVE_STATUSES), config.SCHEDULER_STALE_RUN_MINUTES),
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
            from pipeline_runs pr
            left join projects p on p.id = pr.project_id
            order by pr.created_at desc
            limit %s
            """,
            (limit,),
        )
        return [_normalize(row) for row in rows]
    except Exception:
        return []


def create_pipeline_run(run_id=None, pipeline="scrape", project_id=None, status="queued", stage="queued", message=""):
    if not config.DATABASE_URL:
        return None

    run_id = run_id or uuid.uuid4().hex
    payload = {
        "id": run_id,
        "pipeline": pipeline,
        "project_id": project_id,
        "status": status,
        "stage": stage,
        "message": message,
    }

    try:
        db.fetch_one(
            f"""
            insert into pipeline_runs (id, pipeline, project_id, status, stage, message, has_detail)
            values (%s, %s, %s, %s, %s, %s, true)
            on conflict (id) do update set
              pipeline = excluded.pipeline,
              project_id = excluded.project_id,
              status = excluded.status,
              stage = excluded.stage,
              message = excluded.message,
              has_detail = true,
              updated_at = now()
            returning {RUN_COLUMNS}
            """,
            (
                payload["id"],
                payload["pipeline"],
                payload["project_id"],
                payload["status"],
                payload["stage"],
                payload["message"],
            ),
        )
        return _fetch_by_id(run_id)
    except Exception:
        return None


def update_pipeline_run(run_id, **fields):
    if not config.DATABASE_URL or not run_id:
        return None

    allowed = {
        "pipeline",
        "project_id",
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
        "scrape_started_at",
        "scrape_finished_at",
        "clean_started_at",
        "clean_finished_at",
        "enrich_started_at",
        "enrich_finished_at",
    }
    keys = [key for key in fields.keys() if key in allowed]
    if not keys:
        return _fetch_by_id(run_id)

    assignments = ", ".join(f"{key} = %s" for key in keys)
    params = [fields[key] for key in keys] + [run_id]

    try:
        db.fetch_one(
            f"""
            update pipeline_runs
            set {assignments},
                updated_at = now()
            where id = %s
            returning {RUN_COLUMNS}
            """,
            params,
        )
        return _fetch_by_id(run_id)
    except Exception:
        return None


def get_pipeline_run_sources(run_id):
    """Per-source breakdown for one run, ordered by scraped count. Empty for
    legacy runs (no rows were ever written) or runs that failed before enrich.py
    could record anything."""
    if not config.DATABASE_URL or not run_id:
        return []

    try:
        rows = db.fetch_all(
            """
            select source, source_url, scraped, duplicate, blocked, date_filtered, kept, enriched, saved,
                   http_status, network_blocked, fetch_note
            from pipeline_run_sources
            where run_id = %s
            order by scraped desc, source asc
            """,
            (run_id,),
        )
        return [_normalize_source_stat(row) for row in rows]
    except Exception:
        return []


def upsert_pipeline_run_source_stats(run_id, source_stats):
    """Persist the per-source breakdown for a run. `source_stats` is a dict of
    source name -> {scraped, duplicate, blocked, date_filtered, kept, enriched,
    saved, http_status, network_blocked, fetch_note}. Called once at the end
    of enrich.py for runs that have has_detail=true."""
    if not config.DATABASE_URL or not run_id or not source_stats:
        return

    try:
        for source, counts in source_stats.items():
            source_name = (source or "unknown").strip() or "unknown"
            db.execute(
                """
                insert into pipeline_run_sources
                    (run_id, source, source_url, scraped, duplicate, blocked, date_filtered, kept, enriched, saved,
                     http_status, network_blocked, fetch_note)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (run_id, source) do update set
                    source_url = excluded.source_url,
                    scraped = excluded.scraped,
                    duplicate = excluded.duplicate,
                    blocked = excluded.blocked,
                    date_filtered = excluded.date_filtered,
                    kept = excluded.kept,
                    enriched = excluded.enriched,
                    saved = excluded.saved,
                    http_status = excluded.http_status,
                    network_blocked = excluded.network_blocked,
                    fetch_note = excluded.fetch_note,
                    updated_at = now()
                """,
                (
                    run_id,
                    source_name,
                    counts.get("source_url") or None,
                    int(counts.get("scraped") or 0),
                    int(counts.get("duplicate") or 0),
                    int(counts.get("blocked") or 0),
                    int(counts.get("date_filtered") or 0),
                    int(counts.get("kept") or 0),
                    int(counts.get("enriched") or 0),
                    int(counts.get("saved") or 0),
                    counts.get("http_status"),
                    bool(counts.get("network_blocked")),
                    counts.get("fetch_note") or None,
                ),
            )
    except Exception as exc:
        print(f"Failed to persist per-source pipeline stats: {exc}")

