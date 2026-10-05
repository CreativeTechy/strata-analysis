-- One-off backfill: force-stop analysis runs left "queued"/"running" by a
-- backend that died mid-run. Those rows block start_or_reuse_analysis_run()
-- for their project until STALE_RUN_MINUTES elapses, and a run whose worker
-- thread is gone can never finish on its own.
--
-- Migrations run at backend startup, before any new worker thread exists, so
-- every run still active at this point has no live worker and is safe to
-- cancel. Articles it left mid-analysis keep their pending status and are
-- picked up by the next scope="pending" run.
update public.pipeline_runs
set status = 'cancelled',
    stage = 'cancelled',
    message = 'Force-stopped by migration: run was stuck with no active worker.',
    cancelled_at = coalesce(cancelled_at, now()),
    finished_at = coalesce(finished_at, now())
where status in ('queued', 'running');
