-- Project-aware evidence relevance with staged, publishable generations.

alter table public.evidence_claims
    add column if not exists generation integer not null default 0,
    add column if not exists relevance text not null default 'unclassified',
    add column if not exists relevance_explanation text,
    add column if not exists relevance_score numeric,
    add column if not exists relevance_status text not null default 'unclassified',
    add column if not exists relevance_model text,
    add column if not exists scope_hash text;

alter table public.evidence_claims
    drop constraint if exists evidence_claims_run_fingerprint_key;
alter table public.evidence_claims
    drop constraint if exists evidence_claims_run_generation_fingerprint_key;
alter table public.evidence_claims
    add constraint evidence_claims_run_generation_fingerprint_key
    unique (run_id, generation, fingerprint);
alter table public.evidence_claims
    drop constraint if exists evidence_claims_relevance_check;
alter table public.evidence_claims
    add constraint evidence_claims_relevance_check
    check (relevance in ('direct','contextual','unrelated','uncertain','unclassified'));
alter table public.evidence_claims
    drop constraint if exists evidence_claims_relevance_status_check;
alter table public.evidence_claims
    add constraint evidence_claims_relevance_status_check
    check (relevance_status in ('success','failed','unclassified'));

create index if not exists evidence_claims_generation_idx
    on public.evidence_claims (run_id, generation, active, relevance);

alter table public.evidence_run_status
    add column if not exists scope_snapshot jsonb,
    add column if not exists scope_hash text,
    add column if not exists active_generation integer not null default 0;

create table if not exists public.evidence_generations (
    run_id text not null references public.pipeline_runs(id) on delete cascade,
    generation integer not null,
    project_id bigint not null references public.projects(id) on delete cascade,
    status text not null default 'pending',
    scope_snapshot jsonb not null default '{}'::jsonb,
    scope_hash text not null,
    rules_version text not null,
    model text,
    candidate_count integer not null default 0,
    classified_count integer not null default 0,
    direct_count integer not null default 0,
    contextual_count integer not null default 0,
    unrelated_count integer not null default 0,
    uncertain_count integer not null default 0,
    error text,
    started_at timestamptz,
    finished_at timestamptz,
    published_at timestamptz,
    created_at timestamptz not null default now(),
    primary key (run_id, generation),
    constraint evidence_generations_status_check
        check (status in ('pending','running','success','failed'))
);

create table if not exists public.evidence_relevance_cache (
    scope_hash text not null,
    fingerprint text not null,
    content_hash text not null default '',
    rules_version text not null,
    model text not null default '',
    relevance text not null,
    explanation text,
    score numeric,
    processing_status text not null default 'success',
    updated_at timestamptz not null default now(),
    primary key (scope_hash, fingerprint, content_hash, rules_version, model),
    constraint evidence_relevance_cache_label_check
        check (relevance in ('direct','contextual','unrelated','uncertain')),
    constraint evidence_relevance_cache_status_check
        check (processing_status in ('success','failed'))
);

create table if not exists public.evidence_relevance_reviews (
    id bigint generated always as identity primary key,
    project_id bigint not null references public.projects(id) on delete cascade,
    run_id text not null references public.pipeline_runs(id) on delete cascade,
    fingerprint text not null,
    reviewer_id bigint references public.users(id) on delete set null,
    reviewer_name text,
    decision text not null,
    reason text not null,
    created_at timestamptz not null default now(),
    constraint evidence_relevance_reviews_decision_check
        check (decision in ('direct','contextual','unrelated','uncertain'))
);
create index if not exists evidence_relevance_reviews_lookup_idx
    on public.evidence_relevance_reviews (project_id, run_id, fingerprint, created_at desc);

-- Existing claims remain available but are explicitly legacy/unclassified.
update public.evidence_claims ec
set generation = coalesce((select ers.active_generation from public.evidence_run_status ers where ers.run_id=ec.run_id), 0)
where ec.generation = 0;
