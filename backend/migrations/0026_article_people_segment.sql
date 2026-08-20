-- Open-vocabulary life-situation/occupation classification of the people
-- quoted/mentioned in an article (structured_extraction.py's people_opinions
-- extraction), so sentiment can be sliced by an arbitrary group like
-- "unemployed" or "small business owner" - "60% of unemployed people are
-- positive" - not just by the closed gender/age_range dimensions added in
-- migration 0025.
--
-- Unlike gender/age_range/region, segment has no fixed vocabulary to
-- validate or canonicalize against, so paraphrases ("jobless", "laid off",
-- "unemployed") are clustered via embedding similarity at save time (see
-- services/articles/store.py's _resolve_segment_label - same
-- attach-or-create pattern as idea_clusters, but a flat global vocabulary
-- instead of a project-scoped one). article_people_opinions keeps both the
-- LLM's raw phrase (segment_raw) and the resolved canonical label (segment);
-- articles gets a majority-vote rollup of the canonical label, same pattern
-- migration 0025 used for region/gender/age_range.
alter table public.article_people_opinions
    add column if not exists segment_raw text not null default 'unknown',
    add column if not exists segment text not null default 'unknown';

alter table public.articles
    add column if not exists segment text not null default 'unknown';

create index if not exists articles_segment_idx on public.articles (segment);

create table if not exists public.segment_taxonomy (
    id              bigint generated always as identity primary key,
    canonical_label text not null unique,
    embedding_json  jsonb default '[]'::jsonb,
    embedding_model text,
    embedding_source text,
    embedded_at     timestamptz,
    first_seen_at   timestamptz default now(),
    last_seen_at    timestamptz default now()
);
