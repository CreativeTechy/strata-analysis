-- Evidence source-quality, passage-relevance, and unsupported-candidate audit trail.

alter table public.evidence_generations
    add column if not exists source_article_count integer not null default 0,
    add column if not exists usable_article_count integer not null default 0,
    add column if not exists excluded_article_count integer not null default 0,
    add column if not exists duplicate_article_count integer not null default 0,
    add column if not exists unsupported_candidate_count integer not null default 0,
    add column if not exists pending_review_count integer not null default 0,
    add column if not exists decision_method text,
    add column if not exists decision_config jsonb not null default '{}'::jsonb,
    add column if not exists timings jsonb not null default '{}'::jsonb;

alter table public.evidence_claims
    add column if not exists relevance_method text,
    add column if not exists relevance_config jsonb not null default '{}'::jsonb;

create table if not exists public.evidence_article_screenings (
    run_id text not null references public.pipeline_runs(id) on delete cascade,
    generation integer not null,
    project_id bigint not null references public.projects(id) on delete cascade,
    article_id bigint not null references public.articles(id) on delete cascade,
    content_hash text not null,
    duplicate_key text not null,
    decision text not null,
    quality_code text not null,
    reason text not null,
    best_passage text,
    passage_score numeric,
    relevance text not null,
    decision_method text not null,
    model text,
    decision_config jsonb not null default '{}'::jsonb,
    rules_version text not null,
    created_at timestamptz not null default now(),
    primary key (run_id, generation, article_id),
    constraint evidence_article_screenings_decision_check
        check (decision in ('included','excluded','needs_review')),
    constraint evidence_article_screenings_relevance_check
        check (relevance in ('direct','contextual','unrelated','uncertain'))
);
create index if not exists evidence_article_screenings_review_idx
    on public.evidence_article_screenings (project_id, run_id, generation, decision, quality_code);

create table if not exists public.evidence_article_screening_reviews (
    id bigint generated always as identity primary key,
    project_id bigint not null references public.projects(id) on delete cascade,
    run_id text not null references public.pipeline_runs(id) on delete cascade,
    article_id bigint not null references public.articles(id) on delete cascade,
    reviewer_id bigint references public.users(id) on delete set null,
    reviewer_name text,
    decision text not null,
    reason text not null,
    created_at timestamptz not null default now(),
    constraint evidence_article_screening_reviews_decision_check
        check (decision in ('include','exclude','needs_review'))
);
create index if not exists evidence_article_screening_reviews_lookup_idx
    on public.evidence_article_screening_reviews (project_id, run_id, article_id, created_at desc);

create table if not exists public.evidence_claim_candidates (
    run_id text not null references public.pipeline_runs(id) on delete cascade,
    generation integer not null,
    project_id bigint not null references public.projects(id) on delete cascade,
    article_id bigint not null references public.articles(id) on delete cascade,
    fingerprint text not null,
    topic text not null,
    claim_text text not null,
    passage text,
    status text not null,
    reason text not null,
    decision_method text not null,
    rules_version text not null,
    created_at timestamptz not null default now(),
    primary key (run_id, generation, article_id, fingerprint),
    constraint evidence_claim_candidates_status_check
        check (status in ('accepted','rejected','needs_review'))
);
create index if not exists evidence_claim_candidates_review_idx
    on public.evidence_claim_candidates (project_id, run_id, generation, status);

create table if not exists public.evidence_passage_relevance_cache (
    scope_hash text not null,
    content_hash text not null,
    rules_version text not null,
    model text not null,
    decision_config_hash text not null,
    relevance text not null,
    score numeric,
    passage text,
    reason text not null,
    updated_at timestamptz not null default now(),
    primary key (scope_hash, content_hash, rules_version, model, decision_config_hash),
    constraint evidence_passage_relevance_cache_label_check
        check (relevance in ('direct','contextual','unrelated','uncertain'))
);
