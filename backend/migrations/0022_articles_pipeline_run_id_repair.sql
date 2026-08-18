-- Repairs pipeline_run_id values corrupted by a bug in the upsert's
-- on-conflict clause (fixed in application code alongside this migration):
-- it preferred the incoming run's id over the value already stored, so any
-- run that re-crawled a URL an earlier run had already saved - which
-- happens on every run, since each run re-crawls all of a project's
-- sources, not just newly added ones - stole that article's run
-- attribution. In practice this meant whichever run happened to run most
-- recently ended up "owning" every article the project had ever scraped,
-- while every earlier run showed 0.
--
-- created_at is set once at first insert and is never touched by the
-- upsert, so it still reliably marks which run actually first produced each
-- row. This recomputes pipeline_run_id from that timestamp against each
-- completed run's [started_at, finished_at] window, picking the
-- earliest-started matching run when more than one window contains it
-- (shouldn't normally happen, since a project's runs don't overlap).
with matched as (
    select distinct on (a.id) a.id as article_id, pr.id as run_id
    from articles a
    join article_projects ap on ap.article_id = a.id
    join pipeline_runs pr
        on pr.project_id = ap.project_id
       and pr.pipeline = 'scrape'
       and pr.finished_at is not null
       and pr.started_at <= a.created_at
       and a.created_at <= pr.finished_at
    order by a.id, pr.started_at asc
)
update articles a
set pipeline_run_id = matched.run_id
from matched
where matched.article_id = a.id
  and a.pipeline_run_id is distinct from matched.run_id;
