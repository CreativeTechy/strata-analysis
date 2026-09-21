-- SM-68: reproducible, project-scoped evidence assessments.
alter table public.articles
    add column if not exists source_provenance jsonb;

create table if not exists public.evidence_run_articles (
    run_id          text not null references public.pipeline_runs(id) on delete cascade,
    project_id      bigint not null references public.projects(id) on delete cascade,
    article_id      bigint not null,
    content_hash    text,
    source_snapshot jsonb,
    captured_at     timestamptz not null default now(),
    primary key (run_id, article_id)
);

create index if not exists evidence_run_articles_project_idx
    on public.evidence_run_articles (project_id, run_id);

create table if not exists public.evidence_run_status (
    run_id          text primary key references public.pipeline_runs(id) on delete cascade,
    project_id      bigint not null references public.projects(id) on delete cascade,
    status          text not null default 'pending',
    error           text,
    article_count   integer not null default 0,
    claim_count     integer not null default 0,
    rules_version   text not null default 'evidence-v1',
    started_at      timestamptz,
    finished_at     timestamptz,
    updated_at      timestamptz not null default now(),
    constraint evidence_run_status_check check (status in ('pending','running','success','failed'))
);

create index if not exists evidence_run_status_project_idx
    on public.evidence_run_status (project_id, updated_at desc);

create table if not exists public.evidence_claims (
    id                bigint generated always as identity primary key,
    project_id        bigint not null references public.projects(id) on delete cascade,
    run_id            text not null references public.pipeline_runs(id) on delete cascade,
    source_article_id bigint not null,
    fingerprint       text not null,
    claim_text        text not null,
    claim_type        text not null default 'factual_assertion',
    topic             text not null default 'General',
    entities          jsonb not null default '[]'::jsonb,
    geography         text,
    time_scope        text,
    dates             jsonb not null default '[]'::jsonb,
    quantities        jsonb not null default '[]'::jsonb,
    assessment        text not null default 'insufficient_evidence',
    explanation       text,
    limitations       text,
    processing_status text not null default 'success',
    processing_error  text,
    model             text,
    rules_version     text not null default 'evidence-v1',
    supporting_count  integer not null default 0,
    contradicting_count integer not null default 0,
    contextual_count  integer not null default 0,
    distinct_origins  integer not null default 0,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    constraint evidence_claims_type_check check
        (claim_type in ('factual_assertion','attributed_statement','forecast','opinion','causal_explanation')),
    constraint evidence_claims_assessment_check check
        (assessment in ('supported','contradicted','mixed_evidence','insufficient_evidence','not_yet_verifiable','assessment_unavailable')),
    constraint evidence_claims_processing_check check
        (processing_status in ('pending','success','failed')),
    constraint evidence_claims_run_fingerprint_key unique (run_id, fingerprint)
);

create index if not exists evidence_claims_filter_idx
    on public.evidence_claims (project_id, run_id, topic, assessment);

create table if not exists public.evidence_items (
    id             bigint generated always as identity primary key,
    claim_id       bigint not null references public.evidence_claims(id) on delete cascade,
    article_id     bigint not null,
    relationship   text not null,
    passage        text not null,
    citation_valid boolean not null default false,
    origin_key     text,
    source_snapshot jsonb,
    created_at     timestamptz not null default now(),
    constraint evidence_items_relationship_check check
        (relationship in ('supporting','contradicting','contextual')),
    constraint evidence_items_claim_article_key unique (claim_id, article_id, relationship)
);

create index if not exists evidence_items_claim_idx on public.evidence_items (claim_id);

create table if not exists public.evidence_reviews (
    id             bigint generated always as identity primary key,
    claim_id       bigint not null references public.evidence_claims(id) on delete cascade,
    reviewer_id    bigint references public.users(id) on delete set null,
    reviewer_name  text,
    decision       text not null,
    reason         text not null,
    created_at     timestamptz not null default now(),
    constraint evidence_reviews_decision_check check
        (decision in ('supported','contradicted','mixed_evidence','insufficient_evidence','not_yet_verifiable'))
);

create index if not exists evidence_reviews_claim_idx
    on public.evidence_reviews (claim_id, created_at desc);

create table if not exists public.evidence_provenance_reviews (
    id bigint generated always as identity primary key,
    project_id bigint not null references public.projects(id) on delete cascade,
    article_id bigint not null references public.articles(id) on delete cascade,
    reviewer_id bigint references public.users(id) on delete set null,
    reviewer_name text, status text not null, reason text not null,
    created_at timestamptz not null default now(),
    constraint evidence_provenance_status_check check (status in ('verified','rejected','unassessed'))
);
create index if not exists evidence_provenance_reviews_article_idx
    on public.evidence_provenance_reviews (project_id, article_id, created_at desc);

drop trigger if exists set_evidence_claims_updated_at on public.evidence_claims;
create trigger set_evidence_claims_updated_at
before update on public.evidence_claims
for each row execute function public.set_updated_at();

drop trigger if exists set_evidence_run_status_updated_at on public.evidence_run_status;
create trigger set_evidence_run_status_updated_at
before update on public.evidence_run_status
for each row execute function public.set_updated_at();
