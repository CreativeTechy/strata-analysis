-- Cached article-to-project screening and immutable per-run audit records.

alter table public.article_projects
    add column if not exists relevance_decision text,
    add column if not exists relevance_explanation text,
    add column if not exists relevance_source text,
    add column if not exists relevance_scope_hash text,
    add column if not exists relevance_content_hash text,
    add column if not exists relevance_model text,
    add column if not exists relevance_rules_version text,
    add column if not exists relevance_screened_at timestamptz,
    add column if not exists manual_relevance_override text,
    add column if not exists manual_relevance_reason text,
    add column if not exists manual_relevance_reviewer_id bigint references public.users(id) on delete set null,
    add column if not exists manual_relevance_reviewer_name text,
    add column if not exists manual_relevance_updated_at timestamptz;

alter table public.article_projects
    drop constraint if exists article_projects_relevance_decision_check;
alter table public.article_projects
    add constraint article_projects_relevance_decision_check
    check (relevance_decision is null or relevance_decision in ('accepted','excluded','needs_review'));
alter table public.article_projects
    drop constraint if exists article_projects_manual_relevance_override_check;
alter table public.article_projects
    add constraint article_projects_manual_relevance_override_check
    check (manual_relevance_override is null or manual_relevance_override in ('include','exclude'));

create index if not exists article_projects_relevance_idx
    on public.article_projects (project_id, relevance_decision, similarity_score desc);

alter table public.pipeline_runs
    add column if not exists articles_screened integer not null default 0,
    add column if not exists articles_included integer not null default 0,
    add column if not exists articles_excluded integer not null default 0,
    add column if not exists articles_needs_review integer not null default 0,
    add column if not exists screening_mode text;

alter table public.pipeline_runs
    drop constraint if exists pipeline_runs_screening_mode_check;
alter table public.pipeline_runs
    add constraint pipeline_runs_screening_mode_check
    check (screening_mode is null or screening_mode in ('off','observe','enforce','fallback'));

create table if not exists public.pipeline_run_article_screenings (
    run_id text not null references public.pipeline_runs(id) on delete cascade,
    project_id bigint not null references public.projects(id) on delete cascade,
    article_id bigint not null references public.articles(id) on delete cascade,
    decision text not null,
    included boolean not null,
    similarity_score numeric,
    decision_source text not null,
    explanation text,
    scope_hash text not null,
    content_hash text not null,
    rules_version text not null,
    model text,
    created_at timestamptz not null default now(),
    primary key (run_id, article_id),
    constraint pipeline_run_article_screenings_decision_check
        check (decision in ('accepted','excluded','needs_review'))
);

create index if not exists pipeline_run_article_screenings_run_idx
    on public.pipeline_run_article_screenings (run_id, decision, included);
