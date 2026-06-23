-- Strata Media - Supabase schema for the car-news pipeline.
-- Run this in the Supabase SQL Editor (Dashboard -> SQL Editor -> New query).

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

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists set_feeds_updated_at on public.feeds;
create trigger set_feeds_updated_at
before update on public.feeds
for each row
execute function public.set_updated_at();

alter table public.feeds enable row level security;

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
