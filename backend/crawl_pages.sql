-- Raw spider output (Spider Mode deep crawls). Kept separate from the curated
-- `articles` table so Spark can dedup / sentiment / weight the big volume here
-- without polluting the enriched feed. Run in the Supabase SQL editor.

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

create index if not exists crawl_pages_crawl_idx  on public.crawl_pages (crawl_id);
create index if not exists crawl_pages_source_idx  on public.crawl_pages (source);
create index if not exists crawl_pages_created_idx on public.crawl_pages (created_at desc);

-- Writes come from the spider backend with the service_role key (bypasses RLS).
-- Spark also reads with the service key. No public access needed.
alter table public.crawl_pages enable row level security;
