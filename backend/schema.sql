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
    description  text,
    location     text,
    target_audience text,
    hashtags     jsonb default '[]'::jsonb,
    keywords     jsonb default '[]'::jsonb,
    usernames    jsonb default '[]'::jsonb,
    start_date   date,
    end_date     date,
    embedding_json jsonb default '[]'::jsonb,
    embedding_model text,
    embedding_source text,
    embedded_at  timestamptz,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now()
);

alter table public.events
    add column if not exists description text,
    add column if not exists location text,
    add column if not exists target_audience text,
    add column if not exists hashtags jsonb default '[]'::jsonb,
    add column if not exists keywords jsonb default '[]'::jsonb,
    add column if not exists usernames jsonb default '[]'::jsonb,
    add column if not exists embedding_json jsonb default '[]'::jsonb,
    add column if not exists embedding_model text,
    add column if not exists embedding_source text,
    add column if not exists embedded_at timestamptz,
    add column if not exists repeat_enabled boolean not null default false,
    add column if not exists repeat_interval_value integer,
    add column if not exists repeat_interval_unit text,
    add column if not exists next_run_at timestamptz,
    add column if not exists last_run_at timestamptz,
    add column if not exists last_run_status text;

alter table public.events
    drop constraint if exists events_repeat_interval_unit_check;
alter table public.events
    add constraint events_repeat_interval_unit_check
    check (repeat_interval_unit is null or repeat_interval_unit in ('minutes', 'hours', 'days'));

create table if not exists public.sources (
    id           bigint generated always as identity primary key,
    url          text not null unique,
    name         text,
    enabled      boolean not null default true,
    source_type  text not null default 'rss',
    category     text,
    limited      boolean not null default false,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now()
);

alter table public.sources
    add column if not exists limited boolean not null default false;

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
    cancel_requested_at timestamptz,
    cancelled_at     timestamptz,
    created_at       timestamptz default now(),
    updated_at       timestamptz default now()
);

alter table public.pipeline_runs
    add column if not exists cancel_requested_at timestamptz,
    add column if not exists cancelled_at timestamptz;

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
    source_url      text,
    title           text,
    author          text,
    published       text,
    text            text,
    fetched_at      timestamptz,
    summary         text,
    sentiment       text,
    relevance_score numeric,
    category        text,
    article_category text,
    insight_json    jsonb default '{}'::jsonb,
    analysis_model  text,
    analysis_prompt_version text,
    analyzed_at     timestamptz,
    organizations   jsonb default '[]'::jsonb,
    entities        jsonb default '[]'::jsonb,
    topics          jsonb default '[]'::jsonb,
    key_points      jsonb default '[]'::jsonb,
    risks           jsonb default '[]'::jsonb,
    opportunities   jsonb default '[]'::jsonb,
    brands          jsonb default '[]'::jsonb,
    car_models      jsonb default '[]'::jsonb,
    embedding_json  jsonb default '[]'::jsonb,
    embedding_model text,
    embedding_source text,
    embedded_at     timestamptz,
    created_at      timestamptz default now()
);

alter table public.articles
    add column if not exists embedding_json jsonb default '[]'::jsonb,
    add column if not exists embedding_model text,
    add column if not exists embedding_source text,
    add column if not exists embedded_at timestamptz;

create table if not exists public.event_sources (
    event_id     bigint not null references public.events(id) on delete cascade,
    source_id    bigint not null references public.sources(id) on delete cascade,
    created_at   timestamptz default now(),
    primary key (event_id, source_id)
);

create table if not exists public.article_events (
    article_id   bigint not null references public.articles(id) on delete cascade,
    event_id     bigint not null references public.events(id) on delete cascade,
    similarity_score numeric,
    created_at   timestamptz default now(),
    primary key (article_id, event_id)
);

create index if not exists events_status_idx on public.events (status);
create index if not exists events_created_idx on public.events (created_at desc);
create index if not exists events_next_run_idx on public.events (next_run_at) where repeat_enabled = true;

create index if not exists sources_enabled_idx on public.sources (enabled);
create index if not exists sources_created_idx on public.sources (created_at desc);

create index if not exists pipeline_runs_created_idx on public.pipeline_runs (created_at desc);
create index if not exists pipeline_runs_status_idx on public.pipeline_runs (status);

create index if not exists crawl_pages_crawl_idx on public.crawl_pages (crawl_id);
create index if not exists crawl_pages_source_idx on public.crawl_pages (source);
create index if not exists crawl_pages_created_idx on public.crawl_pages (created_at desc);

create index if not exists articles_published_idx on public.articles (published desc);
create index if not exists articles_sentiment_idx on public.articles (sentiment);
create index if not exists articles_article_category_idx on public.articles (article_category);
create index if not exists articles_analyzed_at_idx on public.articles (analyzed_at desc);

create index if not exists event_sources_event_idx on public.event_sources (event_id);
create index if not exists event_sources_source_idx on public.event_sources (source_id);

create index if not exists article_events_event_idx on public.article_events (event_id);
create index if not exists article_events_article_idx on public.article_events (article_id);
create index if not exists article_events_similarity_idx on public.article_events (similarity_score desc);

drop trigger if exists set_events_updated_at on public.events;
create trigger set_events_updated_at
before update on public.events
for each row
execute function public.set_updated_at();

drop trigger if exists set_sources_updated_at on public.sources;
create trigger set_sources_updated_at
before update on public.sources
for each row
execute function public.set_updated_at();

drop trigger if exists set_pipeline_runs_updated_at on public.pipeline_runs;
create trigger set_pipeline_runs_updated_at
before update on public.pipeline_runs
for each row
execute function public.set_updated_at();

alter table public.events enable row level security;
alter table public.sources enable row level security;
alter table public.pipeline_runs enable row level security;
alter table public.crawl_pages enable row level security;
alter table public.articles enable row level security;
alter table public.event_sources enable row level security;
alter table public.article_events enable row level security;

drop policy if exists "Public read access" on public.events;
create policy "Public read access"
on public.events
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.sources;
create policy "Public read access"
on public.sources
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

drop policy if exists "Public read access" on public.event_sources;
create policy "Public read access"
on public.event_sources
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.article_events;
create policy "Public read access"
on public.article_events
for select
to anon, authenticated
using (true);
