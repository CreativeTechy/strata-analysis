-- 0036 added content_quality_decision to pipeline_run_article_screenings via
-- `create table if not exists`, which is a no-op wherever that table already
-- existed from the feature's original (pre-revert) deployment - so the
-- column never actually landed on any database that still had the old
-- table lying around. Fix as its own alter, safe to run everywhere: a no-op
-- on a database where 0036 really did create the table fresh, and additive
-- on one where it didn't.

alter table public.pipeline_run_article_screenings
    add column if not exists content_quality_decision text;
