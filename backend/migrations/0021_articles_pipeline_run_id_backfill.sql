-- One-time historical backfill for migration 0020: articles saved before
-- pipeline_run_id existed are all NULL, so they have no data under the new
-- per-run dashboard/reports view.
--
-- This only fills in a project's articles when that project has exactly one
-- completed ('scrape', finished) pipeline run on record - in that case every
-- article linked to the project can only have come from that run, so the
-- backfill is exact, not a guess. Projects with zero or multiple completed
-- runs are left untouched: with more than one candidate run there is no
-- reliable way to tell which run actually produced a given pre-tracking
-- article (a time-window match would misattribute anything re-scraped or
-- deduped across runs), so we deliberately leave those as NULL rather than
-- guess wrong.
with single_run_projects as (
    select project_id, min(id) as run_id
    from pipeline_runs
    where pipeline = 'scrape' and finished_at is not null
    group by project_id
    having count(*) = 1
)
update articles a
set pipeline_run_id = srp.run_id
from article_projects ap
join single_run_projects srp on srp.project_id = ap.project_id
where ap.article_id = a.id
  and a.pipeline_run_id is null;
