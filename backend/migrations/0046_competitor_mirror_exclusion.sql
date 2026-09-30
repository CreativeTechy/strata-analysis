-- Lets a competitor-mode project's operator opt a project-document out of
-- the competitor_document*/project_document_articles mirror (see
-- services/competitors/project_document_bridge.py) by deleting the mirrored
-- competitor_documents row through the competitor study's own document list.
--
-- Without this, deleting a mirror row is not durable: the next
-- sync_project_documents_into_competitor_evidence() run (triggered by any
-- later approval anywhere in the project) re-inserts a mirror for every
-- project_documents row unconditionally, silently undoing the deletion.
-- Recorded on project_documents (the source), not on the mirror itself,
-- since the mirror row is exactly what gets deleted - there is nothing left
-- on the competitor side to remember the decision on.
alter table public.project_documents
    add column if not exists competitor_mirror_excluded boolean not null default false;
