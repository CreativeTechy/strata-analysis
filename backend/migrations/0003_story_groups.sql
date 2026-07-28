-- Syndication collapse: group near-identical article bodies into one story.
--
-- Prevalence must be counted per independent story, not per URL. One wire story
-- republished on 30 sites is one story that 30 outlets carried; counting it as
-- 30 independent sources inflates every number in the product.
--
-- `signature` is a 128-permutation MinHash sketch (see backend/dedup.py); the
-- fraction of agreeing positions estimates Jaccard similarity over the body's
-- 4-word shingles. `band_keys` are 16 LSH band hashes: two bodies sharing any
-- band key are candidate duplicates, which turns lookup into one indexed array
-- overlap instead of a scan.
--
-- MinHash rather than SimHash because a fixed Hamming threshold is not scale
-- invariant across article lengths — see the module docstring for the measured
-- failure that motivated it.

-- `signature`/`band_keys` are null for a *singleton* group: an article whose body
-- is too short to profile meaningfully. Such an article is still an independent
-- story — we simply cannot prove it duplicates anything — so it gets its own
-- group rather than being left unassigned. A null band_keys never overlaps, so
-- singletons are naturally excluded from duplicate matching, and downstream
-- counting stays uniform (`count(distinct story_id)`) with no nulls to special-case.
create table if not exists public.story_groups (
    id                   bigint generated always as identity primary key,
    project_id           bigint references public.projects(id) on delete cascade,
    canonical_article_id bigint references public.articles(id) on delete set null,
    signature            integer[],
    band_keys            bigint[],
    member_count         integer not null default 1,
    first_seen_at        timestamptz not null default now(),
    last_seen_at         timestamptz not null default now(),
    created_at           timestamptz not null default now(),
    constraint story_groups_signature_pairing
        check ((signature is null) = (band_keys is null))
);

-- GIN supports the `&&` (overlap) operator used for candidate lookup.
create index if not exists story_groups_band_keys_idx
    on public.story_groups using gin (band_keys);
create index if not exists story_groups_project_idx
    on public.story_groups (project_id);

alter table public.articles
    add column if not exists story_id bigint references public.story_groups(id) on delete set null;

create index if not exists articles_story_idx on public.articles (story_id);

-- Resumable backfill: rows still needing a grouping pass.
create index if not exists articles_story_unassigned_idx
    on public.articles (id)
    where story_id is null;

alter table public.story_groups enable row level security;

-- Matches the convention the rest of the schema uses: the backend connects as
-- the table owner (psycopg) and bypasses RLS; this only governs PostgREST-style
-- anon/authenticated roles, which get read-only access.
drop policy if exists "Public read access" on public.story_groups;
create policy "Public read access"
on public.story_groups
for select
to anon, authenticated
using (true);
