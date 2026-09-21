-- Evidence v2: keep source and analysis snapshots separate, expose citation
-- quality, preserve automated assessment revisions, and represent survey
-- percentages as observations instead of article sentiment.

alter table public.evidence_run_articles
    add column if not exists analysis_snapshot jsonb not null default '{}'::jsonb,
    add column if not exists analysis_source text not null default 'reused',
    add column if not exists analysis_status text not null default 'available';

alter table public.evidence_run_articles
    drop constraint if exists evidence_run_articles_analysis_source_check;
alter table public.evidence_run_articles
    add constraint evidence_run_articles_analysis_source_check
    check (analysis_source in ('run','reused','pending','failed'));

alter table public.evidence_items
    add column if not exists quote_source text not null default 'document_text',
    add column if not exists passage_locator text,
    add column if not exists qualifies boolean not null default true;

alter table public.evidence_claims
    add column if not exists structured_claim jsonb not null default '{}'::jsonb,
    add column if not exists independent_origin_count integer not null default 0,
    add column if not exists citation_checked_count integer not null default 0,
    add column if not exists active boolean not null default true;

alter table public.evidence_run_status
    add column if not exists generation integer not null default 0;

alter table public.evidence_reviews
    drop constraint if exists evidence_reviews_decision_check;
alter table public.evidence_reviews
    add constraint evidence_reviews_decision_check check
    (decision in ('supported','contradicted','mixed_evidence','insufficient_evidence','not_yet_verifiable','assessment_unavailable'));

create table if not exists public.evidence_assessment_revisions (
    id bigint generated always as identity primary key,
    claim_id bigint not null references public.evidence_claims(id) on delete cascade,
    generation integer not null,
    assessment text not null,
    explanation text,
    supporting_count integer not null default 0,
    contradicting_count integer not null default 0,
    contextual_count integer not null default 0,
    distinct_origins integer not null default 0,
    rules_version text not null,
    created_at timestamptz not null default now(),
    constraint evidence_assessment_revisions_unique unique (claim_id, generation)
);
create index if not exists evidence_assessment_revisions_claim_idx
    on public.evidence_assessment_revisions (claim_id, created_at desc);

create table if not exists public.survey_observations (
    id bigint generated always as identity primary key,
    project_id bigint not null references public.projects(id) on delete cascade,
    article_id bigint references public.articles(id) on delete cascade,
    run_id text references public.pipeline_runs(id) on delete set null,
    study_key text not null,
    question text not null,
    answer text not null,
    percentage numeric not null check (percentage between 0 and 100),
    population text,
    cohort_dimension text,
    cohort_value text,
    sample_size integer,
    fieldwork_start date,
    fieldwork_end date,
    source_url text,
    created_at timestamptz not null default now(),
    constraint survey_observations_study_cohort_answer_key
        unique (project_id, study_key, cohort_dimension, cohort_value, answer)
);
create index if not exists survey_observations_project_idx
    on public.survey_observations (project_id, study_key);
