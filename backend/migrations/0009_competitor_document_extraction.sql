-- Extraction results for uploaded competitor documents.
--
-- `status` (added in 0008) already carries 'processing'/'processed'/'failed' -
-- this just adds where the text actually landed.

alter table public.competitor_documents
    add column if not exists extracted_text text,
    add column if not exists extraction_method text,
    add column if not exists extraction_error text,
    add column if not exists extracted_at timestamptz;

alter table public.competitor_documents
    drop constraint if exists competitor_documents_extraction_method_check;
alter table public.competitor_documents
    add constraint competitor_documents_extraction_method_check
    check (extraction_method is null or extraction_method in ('text', 'ocr'));
