-- Persisted competitor-analysis runs, replacing the in-memory-only job
-- registry generate_findings() used before (see job_runs.py). That registry
-- is fine for "did the job I started five minutes ago finish" but useless for
-- "which run wrote this finding" or "which documents has this study already
-- analyzed" - both need to survive the request that created them. Each run
-- gets a sequence number per project, the same convention pipeline_runs uses
-- for "Analysis #N".
create table if not exists public.competitor_analysis_runs (
    id              bigint generated always as identity primary key,
    project_id      bigint not null references public.projects(id) on delete cascade,
    sequence_number integer not null,
    status          text not null default 'queued',
    scope           text not null default 'pending',
    generated       integer not null default 0,
    skipped         jsonb not null default '[]'::jsonb,
    validation      jsonb,
    error           text,
    logs            jsonb not null default '[]'::jsonb,
    started_at      timestamptz not null default now(),
    finished_at     timestamptz,
    constraint competitor_analysis_runs_status_check
        check (status in ('queued', 'running', 'success', 'failed')),
    constraint competitor_analysis_runs_scope_check
        check (scope in ('pending', 'all', 'selected')),
    constraint competitor_analysis_runs_sequence_key unique (project_id, sequence_number)
);

create index if not exists competitor_analysis_runs_project_idx
    on public.competitor_analysis_runs (project_id, sequence_number desc);

-- Which documents' approved articles a *completed* run actually drew evidence
-- from - the basis for a later run's "documents not yet analyzed" scope,
-- without trying to derive that from period_days windows that were never
-- meaningful for document-dated evidence in the first place.
create table if not exists public.competitor_analysis_run_documents (
    run_id      bigint not null references public.competitor_analysis_runs(id) on delete cascade,
    document_id bigint not null references public.competitor_documents(id) on delete cascade,
    primary key (run_id, document_id)
);

create index if not exists competitor_analysis_run_documents_document_idx
    on public.competitor_analysis_run_documents (document_id);

-- Which run generated a given finding, so the reports toolbar can filter by
-- it - separate from pipeline_run_id, which is the unrelated sentiment/AI
-- stage pipeline's run id and is never populated for document-based studies.
alter table public.competitor_findings
    add column if not exists analysis_run_id bigint
        references public.competitor_analysis_runs(id) on delete set null;

create index if not exists competitor_findings_analysis_run_idx
    on public.competitor_findings (analysis_run_id);
