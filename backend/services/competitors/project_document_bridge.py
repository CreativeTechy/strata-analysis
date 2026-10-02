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

Two things this sync deliberately does *not* do, because either would run
over a decision made on the competitor side after the mirror was created:
- Re-approve a mirrored candidate: the upsert only refreshes `article_id`,
  never `status`, on conflict - a mirrored candidate the user rejected from
  the competitor document review stays rejected even though its source
  candidate is (and stays) approved.
- Recreate a mirrored document the user deleted from the competitor document
  list: `project_documents.competitor_mirror_excluded` (migration 0046) is
  set by that delete and checked here, so a project-document opted out this
  way is skipped by every later sync.

What it does actively propagate: a source candidate that leaves 'approved'
(rejected, or un-approved back to 'pending') downgrades its still-'approved'
mirror to 'rejected' - see the second query below. That only touches a
mirror still at 'approved' (i.e. one the competitor side hasn't already
decided on its own), for the same reason as the conflict clause above.

The competitor-naming pass (document_analysis.derive_competitors()) that used
to run automatically at the end of every sync is now a separate function,
refresh_competitors_from_mirrored_evidence() - see its own docstring for why.
Call both from services.projects.project_documents_store.sync_competitor_evidence_after_approval(),
which is every caller's entry point; don't call this module directly from an
API route.
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
    competitor_documents/competitor_document_articles - plain DB upserts, no
    LLM call, safe to run inline on a request. See
    refresh_competitors_from_mirrored_evidence() for the naming pass that
    used to run automatically right after this."""
    project = projects_store.get_project(project_id)
    if not project or project.get("mode") != "competitor":
        return

    documents = db.fetch_all(
        """
        select id, original_filename from project_documents
        where project_id = %s and not competitor_mirror_excluded
        """,
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
        # Only refreshes article_id on conflict - never status. A mirrored
        # candidate the competitor side has already reviewed (approved or
        # rejected) keeps that decision; only a first-time insert (a brand
        # new mirror row) defaults to 'approved', matching the source
        # candidate's own already-approved status.
        db.execute(
            """
            insert into competitor_document_articles
                (document_id, project_id, title, summary, body, status, article_id,
                 source_project_document_article_id)
            select %s, pda.project_id, pda.title, pda.summary, pda.body, 'approved', pda.article_id, pda.id
            from project_document_articles pda
            where pda.document_id = %s and pda.status = 'approved' and pda.article_id is not null
            on conflict (source_project_document_article_id) do update
               set article_id = excluded.article_id
            """,
            (mirrored["id"], document["id"]),
        )
        # Propagates a source candidate leaving 'approved' (rejected, or
        # un-approved back to 'pending') onto its mirror - but only a mirror
        # still at 'approved', i.e. one nobody has reviewed on the competitor
        # side yet. A mirror the competitor side already rejected is left
        # alone (it's already where this would have taken it); a mirror the
        # competitor side re-approved on its own is likewise left alone, that
        # being a decision made after this bridge created it.
        db.execute(
            """
            update competitor_document_articles cda
               set status = 'rejected'
              from project_document_articles pda
             where cda.source_project_document_article_id = pda.id
               and pda.document_id = %s
               and pda.status != 'approved'
               and cda.status = 'approved'
            """,
            (document["id"],),
        )


def refresh_competitors_from_mirrored_evidence(project_id: int) -> None:
    """Names the companies the project's approved articles (mirrored or not)
    are actually about, over the *whole* current evidence set - the same
    full-corpus LLM call document_analysis.derive_competitors() always makes,
    not an incremental one scoped to what this particular sync just mirrored.

    Kept separate from sync_project_documents_into_competitor_evidence() (the
    cheap DB-only mirror) so a caller with a FastAPI BackgroundTasks object
    can schedule this off the request instead of paying for it inline -
    otherwise every approval or import in a competitor-mode project blocks on
    a COMPETITOR_NAMING_TIMEOUT_SECONDS-bounded LLM call over every approved
    article in the study, not just the ones this call just added."""
    try:
        document_analysis.derive_competitors(project_id)
    except Exception:
        # Best-effort, same reasoning as _try_approve_document_candidates:
        # the mirror rows already landed, so evidence is available for
        # "Run analysis" even if this particular naming pass fails.
        logger.exception("derive_competitors failed after syncing project-document evidence for project %s", project_id)
