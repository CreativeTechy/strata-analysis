-- Cross-source idea comparison: which of a project's idea_clusters are
-- talked about by more than one distinct source, and what each source
-- specifically says about it (e.g. one source stating a price/figure that
-- another source states differently for the same idea).
--
-- `value` on idea_cluster_articles is the per-article-occurrence fact this
-- article's frequent_ideas entry carried (see analysis/normalize.py's
-- normalize_frequent_ideas) - e.g. "$98/barrel". It lives on the join row,
-- not on idea_clusters itself, because the whole point is that different
-- articles contributing to the same cluster can carry different values.
alter table public.idea_cluster_articles
    add column if not exists value text;

-- One row per (project, idea_cluster) - the last-generated comparison card
-- for that idea, refreshed in place (see services/articles/idea_comparisons.py)
-- rather than accumulating history, the same "cache, not a log" shape
-- project_trend_summaries uses for its LLM-generated paragraph.
create table if not exists public.idea_comparisons (
    id              bigint generated always as identity primary key,
    project_id      bigint not null references public.projects(id) on delete cascade,
    idea_cluster_id bigint not null references public.idea_clusters(id) on delete cascade,
    idea            text not null,
    type            text not null default 'issue',
    diverges        boolean not null default false,
    sources         jsonb not null default '[]'::jsonb,
    summary         text,
    article_count   integer not null default 0,
    analysis_model  text,
    prompt_version  text,
    generated_at    timestamptz not null default now(),
    constraint idea_comparisons_unique_key unique (project_id, idea_cluster_id)
);

create index if not exists idea_comparisons_project_idx
    on public.idea_comparisons (project_id, diverges desc, article_count desc);
