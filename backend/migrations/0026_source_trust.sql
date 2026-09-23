-- Operator-set trust tier for a project's sources - the Sources tab (see
-- services/articles/articles_query.py's list_project_sources()). Fully
-- offline: no reputation feed, no network corroboration - see the earlier
-- GDELT-based "source reliability" feature (removed in f72fb52) for why that
-- matters in this fork.
--
-- Keyed on the exact same `key` string list_project_sources() already groups
-- by - `real:<host>` for an article that carries its own URL, `document:
-- <source_url>` for an uploaded document with no publisher identity - so
-- attaching a tier to a source group already on screen needs no extra
-- resolution logic. No project_id column: a `real:` key is a publisher
-- hostname, meaningfully the same trust judgement in every project; a
-- `document:` key already embeds one project's own document id in its
-- source_url, so it is already scoped without one.
--
-- 'unknown' (not yet assessed) is deliberately its own tier, distinct from
-- 'untrusted' (assessed and rejected) - collapsing the two is exactly what
-- made the older boolean articles.verified column useless as a trust signal.
create table if not exists public.source_trust (
    id             bigint generated always as identity primary key,
    source_key     text not null unique,
    source_type    text not null,
    tier           text not null,
    reason         text,
    set_by_user_id bigint references public.users(id) on delete set null,
    set_by_name    text,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now(),
    constraint source_trust_type_check check (source_type in ('real', 'document')),
    constraint source_trust_tier_check check (tier in ('trusted', 'mixed', 'untrusted', 'unknown'))
);

drop trigger if exists set_source_trust_updated_at on public.source_trust;
create trigger set_source_trust_updated_at before update on public.source_trust
for each row execute function public.set_updated_at();

-- Append-only audit trail, one row per change - source_trust itself only
-- ever holds the current tier (upserted in place), same split as
-- evidence_provenance_reviews/articles.source_provenance.
create table if not exists public.source_trust_reviews (
    id             bigint generated always as identity primary key,
    source_key     text not null,
    source_type    text not null,
    tier           text not null,
    reason         text not null,
    set_by_user_id bigint references public.users(id) on delete set null,
    set_by_name    text,
    created_at     timestamptz not null default now(),
    constraint source_trust_reviews_tier_check check (tier in ('trusted', 'mixed', 'untrusted', 'unknown'))
);
create index if not exists source_trust_reviews_key_idx on public.source_trust_reviews (source_key, created_at desc);
