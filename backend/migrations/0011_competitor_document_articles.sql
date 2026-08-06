-- Turns extracted document text into reviewable "article" candidates, so an
-- offline study can feed the same competitor_articles/article_projects
-- machinery scraped pages already use (see competitor_analysis.py) instead of
-- a second, document-only analysis path.
--
-- Lifecycle: a document's extraction success kicks off candidate generation
-- (articles_status: pending -> generating -> ready/failed; 'skipped' when
-- extraction itself failed, so there is nothing to generate from). Each
-- candidate then goes through its own pending -> approved/rejected review -
-- approving materializes it into `articles` (article_id backfilled then).

alter table public.competitor_documents
    add column if not exists articles_status text not null default 'pending',
    add column if not exists articles_error text;

alter table public.competitor_documents
    drop constraint if exists competitor_documents_articles_status_check;
alter table public.competitor_documents
    add constraint competitor_documents_articles_status_check
    check (articles_status in ('pending', 'generating', 'ready', 'failed', 'skipped'));

create table if not exists public.competitor_document_articles (
    id            bigint generated always as identity primary key,
    document_id   bigint not null references public.competitor_documents(id) on delete cascade,
    project_id    bigint not null references public.projects(id) on delete cascade,
    title         text not null,
    summary       text,
    body          text not null,
    status        text not null default 'pending',
    article_id    bigint references public.articles(id) on delete set null,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

alter table public.competitor_document_articles
    drop constraint if exists competitor_document_articles_status_check;
alter table public.competitor_document_articles
    add constraint competitor_document_articles_status_check
    check (status in ('pending', 'approved', 'rejected'));

create index if not exists competitor_document_articles_document_idx
    on public.competitor_document_articles (document_id);
create index if not exists competitor_document_articles_project_idx
    on public.competitor_document_articles (project_id, status);

drop trigger if exists set_competitor_document_articles_updated_at on public.competitor_document_articles;
create trigger set_competitor_document_articles_updated_at
before update on public.competitor_document_articles
for each row
execute function public.set_updated_at();

alter table public.competitor_document_articles enable row level security;

drop policy if exists "Public read access" on public.competitor_document_articles;
create policy "Public read access" on public.competitor_document_articles
    for select to anon, authenticated using (true);
