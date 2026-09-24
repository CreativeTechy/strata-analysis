-- Caches the "variation from yesterday" section of the Reports page's
-- Export Summary PDF (services/reports/yesterday_comparison.py): the
-- verified day-over-day metrics this app computes itself, plus the LLM
-- narrative built from them. One row per (project, report scope, comparison
-- dates) - regenerating an export for the same scope/dates re-derives the
-- metrics and compares data_fingerprint (a hash of the exact article
-- snapshots on each side) before spending another LLM call; a fingerprint
-- match means the underlying analysis data has not changed since the cached
-- row was written, same reasoning as project_trend_summaries' cache but
-- validated against the data itself rather than just an article count.
--
-- Deliberately keeps the verified metrics (today_metrics/yesterday_metrics/
-- coverage) even when narrative is null: an LLM failure must not lose the
-- numbers this app already computed with certainty (see
-- yesterday_comparison.py's llm_failed status) - only the narrative,
-- evidence and status describe whether the LLM step itself succeeded.
create table if not exists public.project_report_variation_summaries (
    id                  bigint generated always as identity primary key,
    project_id          bigint not null references public.projects(id) on delete cascade,
    -- 'period:7d' / 'period:30d' / 'period:all' / 'run:<run_id>' - one string
    -- so the natural key stays a plain unique constraint (see
    -- project_trend_summaries' run_id='' comment for why a nullable column
    -- would not dedupe the way this needs to).
    scope_key           text not null,
    today_date          date not null,
    yesterday_date      date not null,
    timezone            text not null default 'UTC',
    status              text not null,
    reason              text,
    today_metrics       jsonb,
    yesterday_metrics   jsonb,
    deltas              jsonb,
    coverage            jsonb,
    data_fingerprint    text not null default '',
    narrative           text,
    evidence            jsonb not null default '[]'::jsonb,
    analysis_model      text,
    prompt_version      text,
    generated_at        timestamptz not null default now(),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint project_report_variation_summaries_scope_key
        unique (project_id, scope_key, today_date, yesterday_date),
    constraint project_report_variation_summaries_status_check
        check (status in ('ok', 'unavailable', 'llm_failed'))
);

create index if not exists project_report_variation_summaries_project_idx
    on public.project_report_variation_summaries (project_id);

drop trigger if exists set_project_report_variation_summaries_updated_at
    on public.project_report_variation_summaries;
create trigger set_project_report_variation_summaries_updated_at
before update on public.project_report_variation_summaries
for each row
execute function public.set_updated_at();
