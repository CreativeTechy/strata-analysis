-- Localized (non-canonical) renderings of a project's trend summary
-- (services/intelligence/trend_summary.py). The canonical summary stays in
-- project_trend_summaries (English, unchanged by this migration) so search,
-- grouping, and cross-document comparisons keep reading a stable value; a
-- requested output locale other than the default is rendered from that
-- canonical text and cached here instead, separately, keyed by the canonical
-- row's own `updated_at` (source_updated_at) so a later canonical
-- regeneration invalidates the localized row without an explicit cascade -
-- trend_summary.py just re-renders it the next time it's requested.
create table if not exists public.project_trend_summaries_localized (
    id                bigint generated always as identity primary key,
    project_id        bigint not null references public.projects(id) on delete cascade,
    period            text not null,
    run_id            text not null default '',
    locale            text not null,
    summary           text not null,
    source_updated_at timestamptz,
    model             text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    constraint project_trend_summaries_localized_scope_key unique (project_id, period, run_id, locale)
);

create index if not exists project_trend_summaries_localized_project_idx
    on public.project_trend_summaries_localized (project_id, locale);

drop trigger if exists set_project_trend_summaries_localized_updated_at on public.project_trend_summaries_localized;
create trigger set_project_trend_summaries_localized_updated_at
before update on public.project_trend_summaries_localized
for each row
execute function public.set_updated_at();
