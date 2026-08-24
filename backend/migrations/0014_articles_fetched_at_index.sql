-- The Articles dashboard page filters by when an article entered the system
-- (fetched_at) via added_from/added_to query params - see articles_store.py's
-- _where_parts. Index it the same way published/analyzed_at already are.
create index if not exists articles_fetched_at_idx on public.articles (fetched_at desc);
