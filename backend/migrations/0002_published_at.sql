-- Give articles a real publish timestamp.
--
-- `articles.published` is free text (whatever the feed emitted) and was being
-- parsed in Python on every read, falling back to `created_at` when parsing
-- failed. That fallback silently turns "when it was said" into "when we scraped
-- it", which makes every time series wrong in a way nobody can see.
--
-- `published` is kept untouched as provenance. `published_at` is the parsed
-- value; `published_precision` records how much of it the source actually gave
-- us, so trend math can exclude rows it cannot place in time.
--   exact   - the source carried a time
--   day     - the source carried a calendar date only
--   unknown - nothing usable; published_at stays null

alter table public.articles
    add column if not exists published_at timestamptz,
    add column if not exists published_precision text;

alter table public.articles
    drop constraint if exists articles_published_precision_check;
alter table public.articles
    add constraint articles_published_precision_check
    check (published_precision is null
           or published_precision in ('exact', 'day', 'unknown'));

-- Trend and "latest" queries order by this; partial index keeps it small by
-- skipping the rows that have no usable date.
create index if not exists articles_published_at_idx
    on public.articles (published_at desc)
    where published_at is not null;

-- Backfill progress is resumable: rows still needing a pass are exactly those
-- with a non-empty `published` and a null `published_precision`.
create index if not exists articles_published_unparsed_idx
    on public.articles (id)
    where published_precision is null;
