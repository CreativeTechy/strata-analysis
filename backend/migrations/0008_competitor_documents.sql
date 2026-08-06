-- Offline competitor studies: documents uploaded instead of scraping the web.
--
-- Extraction (parsing these into text/competitors) is deliberately not built
-- yet - this only records what was uploaded and where it landed on disk, so
-- the upload step has something durable to point at. `status` already carries
-- the values a later extraction pass will need so that work won't need its
-- own migration.

create table if not exists public.competitor_documents (
    id                bigint generated always as identity primary key,
    project_id        bigint not null references public.projects(id) on delete cascade,
    original_filename text not null,
    storage_path      text not null,
    mime_type         text,
    size_bytes        bigint not null default 0,
    status            text not null default 'uploaded',
    created_at        timestamptz not null default now()
);

alter table public.competitor_documents
    drop constraint if exists competitor_documents_status_check;
alter table public.competitor_documents
    add constraint competitor_documents_status_check
    check (status in ('uploaded', 'processing', 'processed', 'failed'));

create index if not exists competitor_documents_project_idx
    on public.competitor_documents (project_id, created_at desc);

alter table public.competitor_documents enable row level security;

drop policy if exists "Public read access" on public.competitor_documents;
create policy "Public read access" on public.competitor_documents
    for select to anon, authenticated using (true);
