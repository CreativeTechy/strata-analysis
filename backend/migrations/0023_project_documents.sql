-- Offline opinion-monitor projects: documents uploaded instead of scraping the
-- web. Mirrors competitor_documents/competitor_document_chunks/
-- competitor_document_articles (migrations 0008/0010/0011) table-for-table,
-- kept as separate tables rather than reused ones so the two domains stay
-- decoupled - see services/projects/project_documents_store.py and
-- services/projects/project_document_articles.py for the pipeline that reads
-- and writes them.
--
-- Lifecycle is identical to the competitor pipeline: a document goes
-- uploaded -> processing -> processed/failed as its chunks extract, then
-- (if extraction produced text) articles_status goes pending -> generating ->
-- ready/failed, or 'skipped' when extraction itself failed. Each candidate
-- article then goes through its own pending -> approved/rejected review;
-- approving materializes it into `articles` (article_id backfilled then) and
-- queues the same sentiment/topic analysis a scraped article gets.

create table if not exists public.project_documents (
    id                bigint generated always as identity primary key,
    project_id        bigint not null references public.projects(id) on delete cascade,
    original_filename text not null,
    storage_path      text not null,
    mime_type         text,
    size_bytes        bigint not null default 0,
    status            text not null default 'uploaded',
    extracted_text    text,
    extraction_method text,
    extraction_error  text,
    extracted_at      timestamptz,
    total_chunks      integer,
    processed_chunks  integer not null default 0,
    articles_status   text not null default 'pending',
    articles_error    text,
    created_at        timestamptz not null default now()
);

alter table public.project_documents
    drop constraint if exists project_documents_status_check;
alter table public.project_documents
    add constraint project_documents_status_check
    check (status in ('uploaded', 'processing', 'processed', 'failed'));

alter table public.project_documents
    drop constraint if exists project_documents_extraction_method_check;
alter table public.project_documents
    add constraint project_documents_extraction_method_check
    check (extraction_method is null or extraction_method in ('text', 'ocr', 'mixed'));

alter table public.project_documents
    drop constraint if exists project_documents_articles_status_check;
alter table public.project_documents
    add constraint project_documents_articles_status_check
    check (articles_status in ('pending', 'generating', 'ready', 'failed', 'skipped'));

create index if not exists project_documents_project_idx
    on public.project_documents (project_id, created_at desc);

alter table public.project_documents enable row level security;

drop policy if exists "Public read access" on public.project_documents;
create policy "Public read access" on public.project_documents
    for select to anon, authenticated using (true);


create table if not exists public.project_document_chunks (
    id            bigint generated always as identity primary key,
    document_id   bigint not null references public.project_documents(id) on delete cascade,
    chunk_index   integer not null,
    text          text,
    method        text,
    error         text,
    created_at    timestamptz not null default now()
);

alter table public.project_document_chunks
    drop constraint if exists project_document_chunks_method_check;
alter table public.project_document_chunks
    add constraint project_document_chunks_method_check
    check (method is null or method in ('text', 'ocr'));

create unique index if not exists project_document_chunks_key
    on public.project_document_chunks (document_id, chunk_index);
create index if not exists project_document_chunks_document_idx
    on public.project_document_chunks (document_id);

alter table public.project_document_chunks enable row level security;

drop policy if exists "Public read access" on public.project_document_chunks;
create policy "Public read access" on public.project_document_chunks
    for select to anon, authenticated using (true);


create table if not exists public.project_document_articles (
    id            bigint generated always as identity primary key,
    document_id   bigint not null references public.project_documents(id) on delete cascade,
    project_id    bigint not null references public.projects(id) on delete cascade,
    title         text not null,
    summary       text,
    body          text not null,
    status        text not null default 'pending',
    article_id    bigint references public.articles(id) on delete set null,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

alter table public.project_document_articles
    drop constraint if exists project_document_articles_status_check;
alter table public.project_document_articles
    add constraint project_document_articles_status_check
    check (status in ('pending', 'approved', 'rejected'));

create index if not exists project_document_articles_document_idx
    on public.project_document_articles (document_id);
create index if not exists project_document_articles_project_idx
    on public.project_document_articles (project_id, status);

drop trigger if exists set_project_document_articles_updated_at on public.project_document_articles;
create trigger set_project_document_articles_updated_at
before update on public.project_document_articles
for each row
execute function public.set_updated_at();

alter table public.project_document_articles enable row level security;

drop policy if exists "Public read access" on public.project_document_articles;
create policy "Public read access" on public.project_document_articles
    for select to anon, authenticated using (true);
