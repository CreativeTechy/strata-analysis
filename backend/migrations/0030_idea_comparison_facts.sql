-- User-supplied facts are durable evidence attached to an idea comparison.
-- They stay separate from the generated comparison cache so regenerating a
-- card can never erase operator input. A per-cluster revision lets the UI
-- identify summaries generated before the latest fact edit or deletion.
create table if not exists public.idea_comparison_facts (
    id                bigint generated always as identity primary key,
    project_id        bigint not null references public.projects(id) on delete cascade,
    idea_cluster_id   bigint not null references public.idea_clusters(id) on delete cascade,
    fact_text          text not null,
    reference_label    text,
    reference_url      text,
    stated_value       text,
    observed_at        date,
    created_by_id      bigint references public.users(id) on delete set null,
    created_by_name    text,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    constraint idea_comparison_facts_text_check check (length(btrim(fact_text)) > 0)
);

create index if not exists idea_comparison_facts_cluster_idx
    on public.idea_comparison_facts (project_id, idea_cluster_id, created_at);

create table if not exists public.idea_comparison_fact_revisions (
    project_id      bigint not null references public.projects(id) on delete cascade,
    idea_cluster_id bigint not null references public.idea_clusters(id) on delete cascade,
    revision        integer not null default 0,
    updated_at      timestamptz not null default now(),
    primary key (project_id, idea_cluster_id)
);

alter table public.idea_comparisons
    add column if not exists facts_revision integer not null default 0;
