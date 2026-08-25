-- A .json/.jsonl document is read by parsing records, not by a text layer or
-- OCR, and _process_record_document records that as method/extraction_method
-- 'records'. Both check constraints predate that path and allow only
-- text/ocr(/mixed), so writing a records chunk failed outright - and failed
-- before the document row moved off 'processing', leaving the upload step
-- spinning with no error to show.
--
-- Drop-then-add rather than a second constraint: the check has to be replaced,
-- not intersected, and `drop ... if exists` keeps the file re-runnable.
alter table public.project_documents
    drop constraint if exists project_documents_extraction_method_check;
alter table public.project_documents
    add constraint project_documents_extraction_method_check
        check (extraction_method is null
               or extraction_method in ('text', 'ocr', 'mixed', 'records'));

alter table public.project_document_chunks
    drop constraint if exists project_document_chunks_method_check;
alter table public.project_document_chunks
    add constraint project_document_chunks_method_check
        check (method is null or method in ('text', 'ocr', 'records'));
