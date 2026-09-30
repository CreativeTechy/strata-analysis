-- Localized (non-canonical) renderings of the Reports page's "Variation from
-- Last Run" narrative (services/reports/yesterday_comparison.py). The
-- canonical narrative stays in project_report_variation_summaries (English,
-- unchanged by this migration) so the PDF export and cross-run comparisons
-- keep reading a stable value; a requested output locale other than the
-- default is rendered from that canonical text and cached here instead,
-- separately, keyed by the canonical row's own `data_fingerprint`
-- (source_fingerprint) so a later canonical regeneration (new/changed
-- articles on either side) invalidates the localized row without an
-- explicit cascade - yesterday_comparison.py just re-renders it the next
-- time it's requested. Same shape as project_trend_summaries_localized
-- (0032), keyed on this feature's own fingerprint instead of a timestamp
-- since that's already how the canonical row itself is invalidated.
create table if not exists public.project_report_variation_summaries_localized (
    id                bigint generated always as identity primary key,
    project_id        bigint not null references public.projects(id) on delete cascade,
    scope_key         text not null,
    today_date        date not null,
    yesterday_date    date not null,
    locale            text not null,
    narrative         text not null,
    source_fingerprint text,
    model             text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    constraint project_report_variation_summaries_localized_scope_key
        unique (project_id, scope_key, today_date, yesterday_date, locale)
);

create index if not exists project_report_variation_summaries_localized_project_idx
    on public.project_report_variation_summaries_localized (project_id, locale);

drop trigger if exists set_project_report_variation_summaries_localized_updated_at
    on public.project_report_variation_summaries_localized;
create trigger set_project_report_variation_summaries_localized_updated_at
before update on public.project_report_variation_summaries_localized
for each row
execute function public.set_updated_at();
