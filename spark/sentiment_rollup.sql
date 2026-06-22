-- Output of the Spark sentiment rollup. One row per brand, de-noised + aggregated.
-- Run in the Supabase SQL editor.

create table if not exists public.sentiment_rollup (
    brand         text primary key,
    mentions      integer,        -- unique (deduped) articles mentioning the brand
    avg_sentiment double precision,  -- -1..1
    positive      integer,
    negative      integer,
    neutral       integer,
    confidence    text,           -- low | medium | high (by sample size)
    updated_at    timestamptz default now()
);

alter table public.sentiment_rollup enable row level security;

-- Let the dashboard read it with the anon key.
drop policy if exists "Public read rollup" on public.sentiment_rollup;
create policy "Public read rollup"
    on public.sentiment_rollup for select to anon, authenticated using (true);
