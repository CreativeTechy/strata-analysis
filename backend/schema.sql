-- Strata Media - Supabase schema for the article analysis pipeline.
-- Run this in Supabase SQL Editor.

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create table if not exists public.events (
    id           bigint generated always as identity primary key,
    name         text not null,
    status       text not null default 'draft',
    start_date   date,
    end_date     date,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now()
);

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

create table if not exists public.pipeline_runs (
    id               text primary key,
    pipeline         text not null default 'scrape',
    status           text not null default 'queued',
    stage            text not null default 'queued',
    message          text,
    articles_scraped integer not null default 0,
    articles_cleaned integer not null default 0,
    articles_saved   integer not null default 0,
    crawl_pages      integer not null default 0,
    error            text,
    event_id         bigint references public.events(id) on delete set null,
    started_at       timestamptz default now(),
    finished_at      timestamptz,
    created_at       timestamptz default now(),
    updated_at       timestamptz default now()
);

create table if not exists public.crawl_pages (
    id          bigint generated always as identity primary key,
    crawl_id    text,
    url         text not null unique,
    source      text,
    seed        text,
    title       text,
    text        text,
    words       integer,
    depth       integer,
    fetched_at  timestamptz,
    created_at  timestamptz default now()
);

create table if not exists public.articles (
    id              bigint generated always as identity primary key,
    url             text not null unique,
    source          text,
    feed            text,
    title           text,
    author          text,
    published       text,
    text            text,
    fetched_at      timestamptz,
    summary         text,
    sentiment       text,
    relevance_score numeric,
    category        text,
    organizations   jsonb default '[]'::jsonb,
    entities        jsonb default '[]'::jsonb,
    topics          jsonb default '[]'::jsonb,
    key_points      jsonb default '[]'::jsonb,
    risks           jsonb default '[]'::jsonb,
    opportunities   jsonb default '[]'::jsonb,
    brands          jsonb default '[]'::jsonb,
    car_models      jsonb default '[]'::jsonb,
    created_at      timestamptz default now()
);

create table if not exists public.event_feeds (
    event_id     bigint not null references public.events(id) on delete cascade,
    feed_id      bigint not null references public.feeds(id) on delete cascade,
    created_at   timestamptz default now(),
    primary key (event_id, feed_id)
);

create table if not exists public.article_events (
    article_id   bigint not null references public.articles(id) on delete cascade,
    event_id     bigint not null references public.events(id) on delete cascade,
    created_at   timestamptz default now(),
    primary key (article_id, event_id)
);

create index if not exists events_status_idx on public.events (status);
create index if not exists events_created_idx on public.events (created_at desc);

create index if not exists feeds_enabled_idx on public.feeds (enabled);
create index if not exists feeds_created_idx on public.feeds (created_at desc);

create index if not exists pipeline_runs_created_idx on public.pipeline_runs (created_at desc);
create index if not exists pipeline_runs_status_idx on public.pipeline_runs (status);

create index if not exists crawl_pages_crawl_idx on public.crawl_pages (crawl_id);
create index if not exists crawl_pages_source_idx on public.crawl_pages (source);
create index if not exists crawl_pages_created_idx on public.crawl_pages (created_at desc);

create index if not exists articles_published_idx on public.articles (published desc);
create index if not exists articles_sentiment_idx on public.articles (sentiment);

create index if not exists event_feeds_event_idx on public.event_feeds (event_id);
create index if not exists event_feeds_feed_idx on public.event_feeds (feed_id);

create index if not exists article_events_event_idx on public.article_events (event_id);
create index if not exists article_events_article_idx on public.article_events (article_id);

drop trigger if exists set_events_updated_at on public.events;
create trigger set_events_updated_at
before update on public.events
for each row
execute function public.set_updated_at();

drop trigger if exists set_feeds_updated_at on public.feeds;
create trigger set_feeds_updated_at
before update on public.feeds
for each row
execute function public.set_updated_at();

drop trigger if exists set_pipeline_runs_updated_at on public.pipeline_runs;
create trigger set_pipeline_runs_updated_at
before update on public.pipeline_runs
for each row
execute function public.set_updated_at();

alter table public.events enable row level security;
alter table public.feeds enable row level security;
alter table public.pipeline_runs enable row level security;
alter table public.crawl_pages enable row level security;
alter table public.articles enable row level security;
alter table public.event_feeds enable row level security;
alter table public.article_events enable row level security;

drop policy if exists "Public read access" on public.events;
create policy "Public read access"
on public.events
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.feeds;
create policy "Public read access"
on public.feeds
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.pipeline_runs;
create policy "Public read access"
on public.pipeline_runs
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.crawl_pages;
create policy "Public read access"
on public.crawl_pages
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.articles;
create policy "Public read access"
on public.articles
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.event_feeds;
create policy "Public read access"
on public.event_feeds
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.article_events;
create policy "Public read access"
on public.article_events
for select
to anon, authenticated
using (true);