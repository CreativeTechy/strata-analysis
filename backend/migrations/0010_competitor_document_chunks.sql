-- Chunked extraction: a document is now processed and stored as one row per
-- page (pdf) / sheet (xlsx, xls) / whole file (everything else), so a large
-- document doesn't need its entire text held in memory at once, progress can
-- be reported per chunk while it's still running, and one bad page/sheet
-- doesn't take the rest of the document down with it.
--
-- competitor_documents.extracted_text (0009) stays as the join of every
-- chunk's text - existing readers of that column don't need to change.
-- extraction_method gains 'mixed' for documents whose chunks disagree (e.g. a
-- PDF with some digital pages and some scanned ones).

create table if not exists public.competitor_document_chunks (
    id            bigint generated always as identity primary key,
    document_id   bigint not null references public.competitor_documents(id) on delete cascade,
    chunk_index   integer not null,
    text          text,
    method        text,
    error         text,
    created_at    timestamptz not null default now()
);

alter table public.competitor_document_chunks
    drop constraint if exists competitor_document_chunks_method_check;
alter table public.competitor_document_chunks
    add constraint competitor_document_chunks_method_check
    check (method is null or method in ('text', 'ocr'));

create unique index if not exists competitor_document_chunks_key
    on public.competitor_document_chunks (document_id, chunk_index);
create index if not exists competitor_document_chunks_document_idx
    on public.competitor_document_chunks (document_id);

alter table public.competitor_document_chunks enable row level security;

drop policy if exists "Public read access" on public.competitor_document_chunks;
create policy "Public read access" on public.competitor_document_chunks
    for select to anon, authenticated using (true);

alter table public.competitor_documents
    add column if not exists total_chunks integer,
    add column if not exists processed_chunks integer not null default 0;

alter table public.competitor_documents
    drop constraint if exists competitor_documents_extraction_method_check;
alter table public.competitor_documents
    add constraint competitor_documents_extraction_method_check
    check (extraction_method is null or extraction_method in ('text', 'ocr', 'mixed'));
