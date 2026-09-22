-- Local, versioned publisher reliability signals imported from Iffy.news.
-- Iffy is a concern list: an absent domain is "not listed", not "verified".
create table if not exists public.source_reliability_datasets (
    id           bigint generated always as identity primary key,
    provider     text not null,
    version      text not null,
    source_url   text not null,
    license      text not null,
    checksum     text not null,
    record_count integer not null,
    active       boolean not null default false,
    imported_at  timestamptz not null default now(),
    unique (provider, version)
);

create unique index if not exists source_reliability_datasets_active_idx
    on public.source_reliability_datasets (provider) where active;

create table if not exists public.source_reliability_ratings (
    dataset_id         bigint not null references public.source_reliability_datasets(id) on delete cascade,
    domain             text not null,
    publisher_name     text,
    factual_rating     text,
    credibility_rating text,
    quality_score      numeric,
    provider_score     numeric,
    review_url         text,
    raw_data           jsonb not null default '{}'::jsonb,
    primary key (dataset_id, domain)
);

create index if not exists source_reliability_ratings_domain_idx
    on public.source_reliability_ratings (domain);

alter table public.articles
    add column if not exists source_domain text,
    add column if not exists source_reliability_status text not null default 'not_assessed',
    add column if not exists source_reliability_reason text,
    add column if not exists source_reliability_provider text,
    add column if not exists source_reliability_reference_url text,
    add column if not exists source_reliability_dataset_version text,
    add column if not exists source_reliability_details jsonb not null default '{}'::jsonb,
    add column if not exists source_reliability_assessed_at timestamptz;

alter table public.articles
    drop constraint if exists articles_source_reliability_status_check;
alter table public.articles
    add constraint articles_source_reliability_status_check
    check (source_reliability_status in ('concern_reported', 'not_listed', 'not_assessed'));

create index if not exists articles_source_reliability_status_idx
    on public.articles (source_reliability_status);
create index if not exists articles_source_domain_idx
    on public.articles (source_domain);

alter table public.project_documents
    add column if not exists publisher_url text;

alter table public.article_analyses
    add column if not exists source_domain text,
    add column if not exists source_reliability_status text not null default 'not_assessed',
    add column if not exists source_reliability_reason text,
    add column if not exists source_reliability_provider text,
    add column if not exists source_reliability_reference_url text,
    add column if not exists source_reliability_dataset_version text,
    add column if not exists source_reliability_details jsonb not null default '{}'::jsonb,
    add column if not exists source_reliability_assessed_at timestamptz;

alter table public.article_analyses
    drop constraint if exists article_analyses_source_reliability_status_check;
alter table public.article_analyses
    add constraint article_analyses_source_reliability_status_check
    check (source_reliability_status in ('concern_reported', 'not_listed', 'not_assessed'));
