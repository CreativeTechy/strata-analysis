"""Postgres-backed analysis run tracking helpers.

A "pipeline run" in this product is one *analysis* run: the AI stage pipeline
(sentiment, tone, topics, demographics - see backend/analysis/) executed over
the articles a project already holds, which here always arrive from uploaded
documents or a JSONL import rather than from the web. There is no scrape stage
and no crawl, so a run only ever has two stages - `prepare` (work out which
articles to analyze) and `analyze` - and its counters are
selected/analyzed/failed rather than scraped/cleaned/saved.

The per-run breakdown is per *document* (pipeline_run_documents) for the same
reason: a document is this product's unit of provenance, the way a configured
source was in a crawler.
"""

import uuid

import config
import db


RUN_COLUMNS = (
    "id,pipeline,project_id,status,stage,message,articles_selected,articles_analyzed,"
    "articles_failed,error,started_at,finished_at,cancel_requested_at,cancelled_at,has_detail,"
    "prepare_started_at,prepare_finished_at,analysis_started_at,analysis_finished_at,created_at,updated_at"
)
# INSERT/UPDATE ... RETURNING can only reference the table being written, so those
# statements use RUN_COLUMNS unqualified; anything reading via a join uses RUN_SELECT.
RUN_SELECT = ",".join(f"pr.{column}" for column in RUN_COLUMNS.split(",")) + ",p.name as project_name"

# Runs in these statuses are still in flight; anything else (success, failed,
# cancelled) is terminal and must not block a new run for the same project.
ACTIVE_STATUSES = ("queued", "running")

# The default pipeline kind. 'competitor-analysis' is the only other one
# written here (see services/competitors/competitor_analysis.py).
ANALYSIS_PIPELINE = "analysis"


def _normalize(row):
    return {
        "id": row.get("id"),
        "pipeline": row.get("pipeline") or ANALYSIS_PIPELINE,
        "project_id": row.get("project_id"),
        "project_name": row.get("project_name"),
        "status": row.get("status") or "queued",
        "stage": row.get("stage") or "queued",
        "message": row.get("message") or "",
        "articles_selected": row.get("articles_selected") or 0,
        "articles_analyzed": row.get("articles_analyzed") or 0,
        "articles_failed": row.get("articles_failed") or 0,
        "error": row.get("error") or "",
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "cancel_requested_at": row.get("cancel_requested_at"),
        "cancelled_at": row.get("cancelled_at"),
        "has_detail": bool(row.get("has_detail")),
        "prepare_started_at": row.get("prepare_started_at"),
        "prepare_finished_at": row.get("prepare_finished_at"),
        "analysis_started_at": row.get("analysis_started_at"),
        "analysis_finished_at": row.get("analysis_finished_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        # This project's Nth analysis run ever, oldest = 1 - stable regardless
        # of how the caller filters/limits/sorts the result set, so the
        # dashboard's "Analysis #N" labels don't shift as older runs age out of
        # a capped list. Populated by list_pipeline_runs() and
        # get_pipeline_run(); a non-analysis pipeline row (e.g.
        # competitor-analysis) has no sequence_number and gets None here.
        "sequence_number": row.get("sequence_number"),
    }


def _normalize_document_stat(row):
    return {
        "document": row.get("document"),
        "document_id": row.get("document_id"),
        "selected": row.get("selected") or 0,
        "analyzed": row.get("analyzed") or 0,
        "failed": row.get("failed") or 0,
        "note": row.get("note") or "",
    }


def _fetch_by_id(run_id):
    row = db.fetch_one(
        f"""
        select {RUN_SELECT}, seq.sequence_number
        from pipeline_runs pr
        left join projects p on p.id = pr.project_id
        left join (
            select id, row_number() over (partition by project_id order by created_at asc) as sequence_number
            from pipeline_runs
            where pipeline = 'analysis'
        ) seq on seq.id = pr.id
        where pr.id = %s
        limit 1
        """,
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
            (int(project_id), list(ACTIVE_STATUSES), config.STALE_RUN_MINUTES),
        )
        return _normalize(row) if row else None
    except Exception:
        return None


def list_pipeline_runs(limit=10, project_id=None):
    if not config.DATABASE_URL:
        return []

    try:
        where_sql = ""
        params = []
        if project_id is not None:
            where_sql = "where pr.project_id = %s"
            params.append(int(project_id))
        params.append(limit)
        rows = db.fetch_all(
            f"""
            select {RUN_SELECT}, seq.sequence_number
            from pipeline_runs pr
            left join projects p on p.id = pr.project_id
            left join (
                select id, row_number() over (partition by project_id order by created_at asc) as sequence_number
                from pipeline_runs
                where pipeline = 'analysis'
            ) seq on seq.id = pr.id
            {where_sql}
            order by pr.created_at desc
            limit %s
            """,
            tuple(params),
        )
        return [_normalize(row) for row in rows]
    except Exception:
        return []


def create_pipeline_run(
    run_id=None,
    pipeline=ANALYSIS_PIPELINE,
    project_id=None,
    status="queued",
    stage="queued",
    message="",
):
    if not config.DATABASE_URL:
        return None

    run_id = run_id or uuid.uuid4().hex

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
            (run_id, pipeline, project_id, status, stage, message),
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
        "articles_selected",
        "articles_analyzed",
        "articles_failed",
        "error",
        "started_at",
        "finished_at",
        "cancel_requested_at",
        "cancelled_at",
        "prepare_started_at",
        "prepare_finished_at",
        "analysis_started_at",
        "analysis_finished_at",
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


def get_pipeline_run_documents(run_id):
    """Per-document breakdown for one run, ordered by how much each document
    contributed. Empty for a run that failed before its prepare stage could
    record anything."""
    if not config.DATABASE_URL or not run_id:
        return []

    try:
        rows = db.fetch_all(
            """
            select document, document_id, selected, analyzed, failed, note
            from pipeline_run_documents
            where run_id = %s
            order by selected desc, document asc
            """,
            (run_id,),
        )
        return [_normalize_document_stat(row) for row in rows]
    except Exception:
        return []


def upsert_pipeline_run_document_stats(run_id, document_stats):
    """Persist the per-document breakdown for a run. `document_stats` is a dict
    of document label -> {document_id, selected, analyzed, failed, note}.
    Called by the analysis pipeline as each document's articles finish, so the
    dashboard fills in document by document rather than only at the end."""
    if not config.DATABASE_URL or not run_id or not document_stats:
        return

    try:
        for document, counts in document_stats.items():
            label = (document or "Unattributed").strip() or "Unattributed"
            db.execute(
                """
                insert into pipeline_run_documents
                    (run_id, document, document_id, selected, analyzed, failed, note)
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (run_id, document) do update set
                    document_id = excluded.document_id,
                    selected = excluded.selected,
                    analyzed = excluded.analyzed,
                    failed = excluded.failed,
                    note = excluded.note,
                    updated_at = now()
                """,
                (
                    run_id,
                    label,
                    counts.get("document_id"),
                    int(counts.get("selected") or 0),
                    int(counts.get("analyzed") or 0),
                    int(counts.get("failed") or 0),
                    counts.get("note") or None,
                ),
            )
    except Exception as exc:
        print(f"Failed to persist per-document analysis stats: {exc}")


def delete_pipeline_run(run_id):
    """Delete one analysis run and everything recorded *about* the run.

    What goes: the `pipeline_runs` row, its per-document breakdown
    (pipeline_run_documents, ON DELETE CASCADE) and its per-article analysis
    snapshots (article_analyses, ON DELETE CASCADE) - i.e. this run stops being
    a comparison point on the dashboard's history charts.

    What stays: the articles themselves and the analysis currently on them.
    `articles.pipeline_run_id` is ON DELETE SET NULL, so an article whose first
    analysis was this run simply loses that attribution; its stored sentiment,
    tone and topics are untouched even when this was the run that produced them.
    Deleting a run discards the *record of a run*, it does not roll the corpus
    back to some earlier state.

    Returns None when there is no such run, and raises ValueError when the run
    is still in flight - stop it first, so its worker isn't still writing
    progress into a row that has been deleted out from under it.
    """
    if not config.DATABASE_URL or not run_id:
        return None

    run = get_pipeline_run(run_id)
    if not run:
        return None
    if run.get("status") in ACTIVE_STATUSES:
        raise ValueError(f"Run is still {run['status']}; stop it before deleting.")

    db.execute("delete from pipeline_runs where id = %s", (str(run_id),))
    return run
