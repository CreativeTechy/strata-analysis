-- A competitor analysis run can now be stopped by the user, which ends it as
-- 'cancelled' (the pipeline_runs mirror already allows that status).
alter table public.competitor_analysis_runs
    drop constraint if exists competitor_analysis_runs_status_check;
alter table public.competitor_analysis_runs
    add constraint competitor_analysis_runs_status_check
    check (status in ('queued', 'running', 'success', 'failed', 'cancelled'));
