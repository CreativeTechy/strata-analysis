"""Bridges a competitor-mode project's Articles-page uploads into the same
evidence pool a competitor study's own document upload produces.

A `mode='competitor'` project can be uploaded to through either wizard: the
regular Articles-page one (project_documents/project_document_articles) or
the competitor study's own (competitor_documents/competitor_document_articles).
Only the second path's approved articles were ever usable as evidence for
that study's "Run analysis"/reports - competitor_analysis.py's evidence query
and analysis_runs_store.py's document picker/scope resolution both read
exclusively from the competitor_document* tables.

Rather than teaching that evidence-selection code a second, parallel source
(which would mean resolving id collisions between two independent id
sequences whenever a scope names specific documents), this mirrors: once a
project-document candidate is approved and materialized into a real
`articles` row, and the owning project is competitor-mode, a corresponding
row is recorded in competitor_documents/competitor_document_articles
pointing at that *same* articles.id. Every existing competitor-side reader
then sees it exactly like a document uploaded through its own wizard, with
no changes needed there.

The mirror is a plain idempotent re-sync, not a one-time copy: calling
sync_project_documents_into_competitor_evidence() re-upserts every currently
-approved project-document candidate for the project every time (keyed on
the unique source_project_document_id/source_project_document_article_id
columns - see migration 0045), so a later approval on either wizard is
picked up the next time this runs without needing to track "what's new".
"""

from __future__ import annotations

import logging

import db
from services.competitors import document_analysis
from services.projects import projects_store

logger = logging.getLogger(__name__)

# Never the real uploaded file's path - the mirror row never re-extracts or
# re-serves the file (the text already lives on project_document_articles/
# articles), so it must not alias the real storage path: a delete/cleanup
# path on the competitor side must never be able to touch the Articles-page
# upload's actual file.
_MIRROR_STORAGE_PATH = "mirrored:project-document/{document_id}"


def sync_project_documents_into_competitor_evidence(project_id: int) -> None:
    """No-op unless `project_id` is a competitor-mode project. Otherwise,
    mirrors every one of its project_documents rows and their currently-
    approved project_document_articles candidates into
    competitor_documents/competitor_document_articles, then re-runs
    document_analysis.derive_competitors() so the mirrored evidence can also
    surface new competitors, not just feed ones already tracked."""
    project = projects_store.get_project(project_id)
    if not project or project.get("mode") != "competitor":
        return

    documents = db.fetch_all(
        "select id, original_filename from project_documents where project_id = %s",
        (int(project_id),),
    )
    if not documents:
        return

    for document in documents:
        mirrored = db.fetch_one(
            """
            insert into competitor_documents
                (project_id, original_filename, storage_path, status, articles_status,
                 source_project_document_id)
            values (%s, %s, %s, 'processed', 'ready', %s)
            on conflict (source_project_document_id) do update
               set original_filename = excluded.original_filename
            returning id
            """,
            (
                int(project_id),
                document["original_filename"],
                _MIRROR_STORAGE_PATH.format(document_id=document["id"]),
                document["id"],
            ),
        )
        db.execute(
            """
            insert into competitor_document_articles
                (document_id, project_id, title, summary, body, status, article_id,
                 source_project_document_article_id)
            select %s, pda.project_id, pda.title, pda.summary, pda.body, 'approved', pda.article_id, pda.id
            from project_document_articles pda
            where pda.document_id = %s and pda.status = 'approved' and pda.article_id is not null
            on conflict (source_project_document_article_id) do update
               set status = 'approved', article_id = excluded.article_id
            """,
            (mirrored["id"], document["id"]),
        )

    try:
        document_analysis.derive_competitors(project_id)
    except Exception:
        # Best-effort, same reasoning as _try_approve_all_and_queue_analysis:
        # the mirror rows above already landed, so evidence is available for
        # "Run analysis" even if this particular naming pass fails.
        logger.exception("derive_competitors failed after syncing project-document evidence for project %s", project_id)
