-- When an article's body last actually changed, as opposed to when it was
-- first seen or last fetched.
--
-- Re-scraping upserts on `url`, and `created_at` is not a mutable field, so it
-- keeps its first-seen value while `fetched_at` moves on every crawl. For a
-- feed item that is right - it was published once. For a page on a competitor's
-- own site it loses the only thing worth knowing: competitor analysis dates
-- `web` pages by `created_at` (their extracted publish dates are copyright
-- years and footer notices, see _effective_date), so a homepage that adds a
-- product, changes a price, or announces a location looks exactly as old as it
-- did the day it was first crawled and can never re-enter the evidence window.
--
-- `content_hash` is over the whitespace-collapsed body, so reflowed markup is
-- not mistaken for news. `content_changed_at` advances only when that hash
-- moves.
--
-- Deliberately added without a default so existing rows stay null: Postgres
-- would otherwise backfill every article with the migration timestamp, which
-- would read as "everything changed at once" and pull the entire archive into
-- the next analysis window. Null means "never observed changing", and callers
-- fall back to created_at. The default applies to rows inserted from here on.
alter table public.articles
    add column if not exists content_hash text,
    add column if not exists content_changed_at timestamptz;

alter table public.articles
    alter column content_changed_at set default now();

-- Analysis filters `web` evidence on this column.
create index if not exists articles_content_changed_idx
    on public.articles (content_changed_at);
