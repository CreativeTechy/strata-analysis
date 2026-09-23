-- A locally imported snapshot of Iffy.news' "Index of Unreliable Sources"
-- (CC BY 4.0, https://iffy.news/index/) - a second, wider seeded default
-- for source_trust.py's trust tiers, alongside the hand-curated
-- trusted_sources.TRUSTED_DOMAINS allowlist. Iffy is a concern list built
-- from Media Bias/Fact Check ratings: a match is useful negative evidence,
-- an absent domain is "not listed", never "verified reliable" - so this
-- only ever seeds a default of 'untrusted', never 'trusted'.
--
-- The running app never contacts Iffy itself - scripts/import_iffy_dataset.py
-- is operator-run tooling that downloads the feed once and stores it here,
-- versioned, same offline-by-default posture as everything else this
-- product analyzes. This is a revival of the dataset-storage half of the
-- source reliability feature reverted in f72fb52 (the half that was never
-- the problem - the GDELT live-lookup half was), trimmed to just what
-- source_trust.py's default-tier resolution needs.
create table if not exists public.source_reliability_datasets (
    id           bigint generated always as identity primary key,
    provider     text not null,
    version      text not null,
    source_url   text not null,
    license      text not null,
    checksum     text not null,
    record_count integer not null,
    active       boolean not null default false,
    imported_at  timestamptz not null default now(),
    unique (provider, version)
);

create unique index if not exists source_reliability_datasets_active_idx
    on public.source_reliability_datasets (provider) where active;

create table if not exists public.source_reliability_ratings (
    dataset_id         bigint not null references public.source_reliability_datasets(id) on delete cascade,
    domain             text not null,
    publisher_name     text,
    factual_rating     text,
    credibility_rating text,
    review_url         text,
    raw_data           jsonb not null default '{}'::jsonb,
    primary key (dataset_id, domain)
);

create index if not exists source_reliability_ratings_domain_idx
    on public.source_reliability_ratings (domain);
