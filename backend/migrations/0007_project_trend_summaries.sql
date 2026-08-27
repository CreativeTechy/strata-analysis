-- Caches the LLM-generated "overall trend" paragraph on the Reports page
-- (services/intelligence/trend_summary.py) so it is not regenerated - and
-- re-billed against the configured LLM - on every page load. One row per
-- (project, period, run scope); run_id is '' rather than null for the
-- period-only view so the natural-key unique constraint actually dedupes it
-- (Postgres treats distinct nulls as non-equal for uniqueness purposes).
create table if not exists public.project_trend_summaries (
    id            bigint generated always as identity primary key,
    project_id    bigint not null references public.projects(id) on delete cascade,
    period        text not null,
    run_id        text not null default '',
    summary       text not null,
    article_count integer not null default 0,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    constraint project_trend_summaries_scope_key unique (project_id, period, run_id)
);

create index if not exists project_trend_summaries_project_idx
    on public.project_trend_summaries (project_id);

drop trigger if exists set_project_trend_summaries_updated_at on public.project_trend_summaries;
create trigger set_project_trend_summaries_updated_at
before update on public.project_trend_summaries
for each row
execute function public.set_updated_at();
