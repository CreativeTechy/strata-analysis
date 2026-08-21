-- Which pipeline run (if any) a finding's evidence was scoped to, mirroring
-- articles.pipeline_run_id (migration 0020). Lets the reports list filter to
-- "cards generated from this pipeline run" the same way Dashboard/Reports
-- filter articles - a finding generated over a period_days date window
-- instead simply has no run to scope to.
alter table public.competitor_findings
    add column if not exists pipeline_run_id text references public.pipeline_runs(id) on delete set null;

create index if not exists competitor_findings_pipeline_run_id_idx
    on public.competitor_findings (pipeline_run_id);
