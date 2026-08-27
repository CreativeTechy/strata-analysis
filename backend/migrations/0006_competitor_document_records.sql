-- Mirrors 0002/0003 for the competitor-study side: a .json/.jsonl/.ndjson
-- upload is read by parsing records, not by a text layer or OCR, and needs
-- the same two things project_document_articles already got.
--
-- record_metadata carries a record's own url/author/published through to
-- _materialize() - without it every imported competitor article would have a
-- NULL published_at, which is what the analysis run's date-window filter
-- keys off. Kept as jsonb for the same reason as the project side: it is
-- provenance from the uploaded file, not app state.
alter table public.competitor_document_articles
    add column if not exists record_metadata jsonb;

-- Both check constraints predate the records path and allow only
-- text/ocr(/mixed); drop-then-add rather than a second constraint since the
-- check has to be replaced, not intersected, and this keeps the file re-runnable.
alter table public.competitor_documents
    drop constraint if exists competitor_documents_extraction_method_check;
alter table public.competitor_documents
    add constraint competitor_documents_extraction_method_check
        check (extraction_method is null
               or extraction_method in ('text', 'ocr', 'mixed', 'records'));

alter table public.competitor_document_chunks
    drop constraint if exists competitor_document_chunks_method_check;
alter table public.competitor_document_chunks
    add constraint competitor_document_chunks_method_check
        check (method is null or method in ('text', 'ocr', 'records'));
