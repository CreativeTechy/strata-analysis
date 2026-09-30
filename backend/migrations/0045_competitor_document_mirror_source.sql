-- Lets a competitor-mode project's Articles-page upload also become usable
-- evidence for that project's competitor study, by mirroring the approved
-- project_documents/project_document_articles rows into
-- competitor_documents/competitor_document_articles (pointing at the same
-- articles.id) rather than teaching competitor_analysis.py/
-- analysis_runs_store.py a second, parallel evidence source. See
-- services/competitors/project_document_bridge.py.
--
-- Nullable and unique: an ordinary competitor-uploaded row never sets this
-- column (Postgres unique constraints allow any number of NULLs), so a
-- mirrored row is distinguishable from a real upload without needing a
-- separate boolean flag, and re-running the mirror sync is a plain
-- on-conflict upsert rather than needing its own duplicate check.
alter table public.competitor_documents
    add column if not exists source_project_document_id bigint
        references public.project_documents(id) on delete cascade;
alter table public.competitor_documents
    drop constraint if exists competitor_documents_source_project_document_key;
alter table public.competitor_documents
    add constraint competitor_documents_source_project_document_key
        unique (source_project_document_id);

alter table public.competitor_document_articles
    add column if not exists source_project_document_article_id bigint
        references public.project_document_articles(id) on delete cascade;
alter table public.competitor_document_articles
    drop constraint if exists competitor_document_articles_source_pda_key;
alter table public.competitor_document_articles
    add constraint competitor_document_articles_source_pda_key
        unique (source_project_document_article_id);
