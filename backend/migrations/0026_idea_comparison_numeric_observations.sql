-- Structured values attached to user-provided facts. Keeping these rows
-- separate allows one fact to contribute several dated observations while
-- preserving the original prose and citation in idea_comparison_facts.
create table if not exists public.idea_comparison_fact_observations (
    id           bigint generated always as identity primary key,
    fact_id      bigint not null references public.idea_comparison_facts(id) on delete cascade,
    metric       text not null,
    numeric_value numeric not null,
    unit         text not null,
    period_label text,
    value_kind   text not null default 'unknown',
    sort_order   integer not null default 0,
    created_at   timestamptz not null default now(),
    constraint idea_comparison_observation_metric_check check (length(btrim(metric)) > 0),
    constraint idea_comparison_observation_unit_check check (length(btrim(unit)) > 0),
    constraint idea_comparison_observation_kind_check
        check (value_kind in ('actual', 'forecast', 'estimate', 'target', 'unknown'))
);

create index if not exists idea_comparison_fact_observations_fact_idx
    on public.idea_comparison_fact_observations (fact_id, sort_order, id);
