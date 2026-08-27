"""Persisted competitor-analysis runs.

generate_findings() used to be tracked only in job_runs.py's in-memory
registry - fine for "did the job I started five minutes ago finish", useless
for "which run wrote this finding" or "which documents has this study already
analyzed", both of which need to survive the request that created them and be
queryable later. This module is that durable half: one row per run,
sequence-numbered per project the same way pipeline_runs numbers
"Analysis #N", plus which documents each *completed* run actually drew
evidence from - the basis for the "documents not yet analyzed" scope option
in the run-analysis dialog.
"""

from __future__ import annotations

from datetime import datetime, timezone

from psycopg.types.json import Jsonb

import db

RUN_COLUMNS = """
    id, project_id, sequence_number, status, scope, generated, skipped,
    validation, error, logs, started_at, finished_at
"""

ACTIVE_STATUSES = ("queued", "running")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_run(project_id: int, scope: str) -> dict:
    return db.fetch_one(
        f"""
        insert into competitor_analysis_runs (project_id, sequence_number, status, scope)
        values (
            %s,
            coalesce(
                (select max(sequence_number) from competitor_analysis_runs where project_id = %s), 0
            ) + 1,
            'queued', %s
        )
        returning {RUN_COLUMNS}
        """,
        (int(project_id), int(project_id), scope),
    )


def get_run(run_id: int) -> dict | None:
    return db.fetch_one(f"select {RUN_COLUMNS} from competitor_analysis_runs where id = %s", (int(run_id),))


def get_active_run(project_id: int) -> dict | None:
    """The most recent queued/running run for this project, if any - a second
    click on "Run analysis" attaches to it instead of starting another."""
    return db.fetch_one(
        f"""
        select {RUN_COLUMNS} from competitor_analysis_runs
         where project_id = %s and status = any(%s)
         order by sequence_number desc
         limit 1
        """,
        (int(project_id), list(ACTIVE_STATUSES)),
    )


def list_runs(project_id: int) -> list[dict]:
    return db.fetch_all(
        f"""
        select {RUN_COLUMNS} from competitor_analysis_runs
         where project_id = %s
         order by sequence_number desc
        """,
        (int(project_id),),
    )


def mark_running(run_id: int) -> None:
    db.execute("update competitor_analysis_runs set status = 'running' where id = %s", (int(run_id),))


def append_log(run_id: int, message: str) -> None:
    db.execute(
        "update competitor_analysis_runs set logs = logs || %s::jsonb where id = %s",
        (Jsonb([{"ts": _now_iso(), "message": message}]), int(run_id)),
    )


def logger(run_id: int):
    """A one-argument `log(message)` to hand to generate_findings, which
    shouldn't have to know it's writing to Postgres versus anywhere else."""
    return lambda message: append_log(run_id, message)


def mark_success(run_id: int, generated: int, skipped: list | None = None,
                 validation: dict | None = None) -> dict | None:
    return db.fetch_one(
        f"""
        update competitor_analysis_runs
           set status = 'success', generated = %s, skipped = %s, validation = %s,
               finished_at = now()
         where id = %s
        returning {RUN_COLUMNS}
        """,
        (int(generated), Jsonb(skipped or []), Jsonb(validation) if validation is not None else None,
         int(run_id)),
    )


def mark_failed(run_id: int, error: str, generated: int = 0, skipped: list | None = None,
                validation: dict | None = None) -> dict | None:
    return db.fetch_one(
        f"""
        update competitor_analysis_runs
           set status = 'failed', error = %s, generated = %s, skipped = %s, validation = %s,
               finished_at = now()
         where id = %s
        returning {RUN_COLUMNS}
        """,
        (error, int(generated), Jsonb(skipped or []), Jsonb(validation) if validation is not None else None,
         int(run_id)),
    )


def record_covered_documents(run_id: int, document_ids: list[int]) -> None:
    if not document_ids:
        return
    db.execute(
        """
        insert into competitor_analysis_run_documents (run_id, document_id)
        select %s, unnest(%s::bigint[])
        on conflict do nothing
        """,
        (int(run_id), [int(d) for d in document_ids]),
    )


def analyzed_document_ids(project_id: int) -> set[int]:
    """Documents any *completed* run already drew evidence from - a failed or
    still-running run never counts, since it did not durably cover anything."""
    rows = db.fetch_all(
        """
        select distinct d.document_id
        from competitor_analysis_run_documents d
        join competitor_analysis_runs r on r.id = d.run_id
        where r.project_id = %s and r.status = 'success'
        """,
        (int(project_id),),
    )
    return {int(row["document_id"]) for row in rows}


def documents_with_scope(project_id: int) -> list[dict]:
    """This study's documents annotated with how many approved articles each
    has and whether a completed run already analyzed it - what the run-
    analysis dialog needs to compute "not yet analyzed" vs "all" vs let the
    user hand-pick specific ones."""
    analyzed = analyzed_document_ids(project_id)
    rows = db.fetch_all(
        """
        select cd.id, cd.original_filename,
               count(cda.id) filter (where cda.status = 'approved') as approved_article_count
          from competitor_documents cd
          left join competitor_document_articles cda on cda.document_id = cd.id
         where cd.project_id = %s
         group by cd.id, cd.original_filename
         order by cd.created_at desc
        """,
        (int(project_id),),
    )
    return [
        {
            **row,
            "approved_article_count": int(row["approved_article_count"] or 0),
            "analyzed": int(row["id"]) in analyzed,
        }
        for row in rows
    ]


def resolve_scope(project_id: int, scope: str, document_ids: list[int] | None = None) -> list[int]:
    """The document ids a run with this scope should draw evidence from -
    always restricted to documents that actually have an approved article, so
    picking "all" or hand-picking one with nothing approved yet can't produce
    a run that silently analyzes zero documents."""
    documents = documents_with_scope(project_id)
    eligible = {int(row["id"]) for row in documents if row["approved_article_count"] > 0}

    if scope == "selected":
        chosen = {int(d) for d in (document_ids or [])}
        return sorted(eligible & chosen)
    if scope == "pending":
        analyzed = {int(row["id"]) for row in documents if row["analyzed"]}
        return sorted(eligible - analyzed)
    return sorted(eligible)  # 'all'
