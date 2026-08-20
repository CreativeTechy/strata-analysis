-- Demographic classification of the people quoted/mentioned in an article
-- (backend/analysis/structured_extraction.py's people_opinions extraction),
-- so sentiment can be sliced by who is expressing it - "50% of quoted women
-- are positive" - not just by article.
--
-- article_people_opinions gets the per-person fields the LLM extracts
-- (defaulting to 'unknown' when the article gives no clear signal - see
-- analysis/labels.py's VALID_GENDERS/VALID_AGE_RANGES). articles gets a
-- deterministic majority-vote rollup of its own opinions' fields (see
-- analysis/aggregation.py's compute_dominant_demographics), the same pattern
-- article_tone/writer_tone already use for overall_tone, so
-- "articles where region = 'Lebanon'" is a plain column filter instead of
-- unpacking the people_opinions jsonb array every query.
alter table public.article_people_opinions
    add column if not exists gender text not null default 'unknown',
    add column if not exists age_range text not null default 'unknown',
    add column if not exists region text not null default 'unknown';

alter table public.articles
    add column if not exists gender text not null default 'unknown',
    add column if not exists age_range text not null default 'unknown',
    add column if not exists region text not null default 'unknown';

create index if not exists articles_gender_idx on public.articles (gender);
create index if not exists articles_age_range_idx on public.articles (age_range);
create index if not exists articles_region_idx on public.articles (region);
