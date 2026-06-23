-- Strata Media - Supabase schema for the car-news pipeline.
-- Run this in the Supabase SQL Editor (Dashboard -> SQL Editor -> New query).

create table if not exists public.pipeline_runs (
    id              text primary key,
    pipeline        text not null default 'scrape',
    status          text not null default 'queued',
    stage           text not null default 'queued',
    message         text,
    articles_scraped integer not null default 0,
    articles_cleaned integer not null default 0,
    articles_saved  integer not null default 0,
    crawl_pages     integer not null default 0,
    error           text,
    started_at      timestamptz default now(),
    finished_at     timestamptz,
    created_at      timestamptz default now(),
    updated_at      timestamptz default now()
);

create index if not exists pipeline_runs_created_idx on public.pipeline_runs (created_at desc);
create index if not exists pipeline_runs_status_idx on public.pipeline_runs (status);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists set_pipeline_runs_updated_at on public.pipeline_runs;
create trigger set_pipeline_runs_updated_at
before update on public.pipeline_runs
for each row
execute function public.set_updated_at();

alter table public.pipeline_runs enable row level security;

drop policy if exists "Public read access" on public.pipeline_runs;
create policy "Public read access"
    on public.pipeline_runs
    for select
    to anon, authenticated
    using (true);

create table if not exists public.feeds (
    id           bigint generated always as identity primary key,
    url          text not null unique,
    name         text,
    enabled      boolean not null default true,
    source_type  text not null default 'rss',
    category     text,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now()
);

create index if not exists feeds_enabled_idx on public.feeds (enabled);
create index if not exists feeds_created_idx on public.feeds (created_at desc);

drop trigger if exists set_feeds_updated_at on public.feeds;
create trigger set_feeds_updated_at
before update on public.feeds
for each row
execute function public.set_updated_at();

alter table public.feeds enable row level security;

create table if not exists public.crawl_pages (
    id          bigint generated always as identity primary key,
    crawl_id    text,                 -- groups one Spider run
    url         text not null unique, -- upsert key
    source      text,
    seed        text,                 -- the seed URL the crawl started from
    title       text,
    text        text,                 -- full extracted article text (for sentiment)
    words       integer,
    depth       integer,
    fetched_at  timestamptz,
    created_at  timestamptz default now()
);

create index if not exists crawl_pages_crawl_idx on public.crawl_pages (crawl_id);
create index if not exists crawl_pages_source_idx on public.crawl_pages (source);
create index if not exists crawl_pages_created_idx on public.crawl_pages (created_at desc);

-- The dashboard and intelligence page read crawl_pages directly.
alter table public.crawl_pages enable row level security;

drop policy if exists "Public read access" on public.crawl_pages;
create policy "Public read access"
    on public.crawl_pages
    for select
    to anon, authenticated
    using (true);

create table if not exists public.articles (
    id              bigint generated always as identity primary key,
    url             text not null unique,          -- upsert key (on_conflict = url)
    source          text,
    feed            text,
    title           text,
    author          text,
    published       text,                           -- raw publish date string from the feed
    text            text,
    fetched_at      timestamptz,
    summary         text,
    sentiment       text,                           -- positive | negative | neutral
    relevance_score numeric,                        -- 1..10
    category        text,                           -- review | event | recall | auction | race | tech | industry | other
    brands          jsonb default '[]'::jsonb,
    car_models      jsonb default '[]'::jsonb,
    created_at      timestamptz default now()
);

create index if not exists articles_published_idx on public.articles (published desc);
create index if not exists articles_sentiment_idx on public.articles (sentiment);

-- Row Level Security: the dashboard reads with the anon key; the scraper
-- writes with the service_role key (which bypasses RLS).
alter table public.articles enable row level security;

drop policy if exists "Public read access" on public.articles;
create policy "Public read access"
    on public.articles
    for select
    to anon, authenticated
    using (true);
