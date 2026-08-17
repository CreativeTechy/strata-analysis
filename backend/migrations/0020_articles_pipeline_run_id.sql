-- Which pipeline run (if any) most recently saved this article, so
-- dashboard/reports stats can be scoped to a single run instead of only a
-- rolling time window. Nullable: articles saved outside a scrape run
-- (manual import, reanalysis, competitor document extraction, or anything
-- saved before this migration) simply have no run to scope to.
alter table public.articles
    add column if not exists pipeline_run_id text references public.pipeline_runs(id) on delete set null;

create index if not exists articles_pipeline_run_id_idx
    on public.articles (pipeline_run_id);
