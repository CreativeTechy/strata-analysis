-- Carries scraper-app's per-article collection provenance across the
-- JSONL export/import boundary. scraper-app stamps every article with
-- pipeline_run_id (a foreign key into *its own* pipeline_runs) plus
-- source_run_snapshot, a denormalized {id, started_at, project_id} copy of
-- the same run identity - the latter is what the export actually carries,
-- since pipeline_run_id would fail a foreign-key constraint here (this
-- database has no such run, and the id would collide in meaning with this
-- app's own pipeline_run_id, which scopes an *analysis* run instead).
--
-- Not a foreign key on this side either: the id it names lives in a
-- different database. Populated at candidate-approval time in
-- services/projects/project_document_articles.py from the record_metadata
-- a JSONL-sourced candidate carries (see services/documents/records.py).
alter table public.articles
    add column if not exists source_run_snapshot jsonb;

comment on column public.articles.source_run_snapshot is
    'Denormalized snapshot of the scraper-app pipeline run that first collected this article - {id, started_at, project_id} - carried through the JSONL export/import boundary. Not a foreign key: the id it names lives in scraper-app''s own database. Null for articles that did not come from a scraper-app export.';
