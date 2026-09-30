-- article_analyses.py's SNAPSHOT_COLUMNS (and fetch_run_article_rows/
-- fetch_state_as_of) read/write an.source_domain, but the migration that
-- originally added it here (0022_source_reliability.sql) was deleted whole by
-- f72fb52's revert of the source-reliability/GDELT feature - which kept
-- source_domain on `articles` (still used by publisher_identity.py/evidence
-- grounding) but dropped it from `article_analyses` along with the rest of
-- that migration. Every record_analysis_snapshot() insert has been failing
-- silently since (caught and logged, by design, so it doesn't fail the
-- article) - leaving article_analyses empty for every run, which is why
-- every finished run shows the dashboard's "No analytical dataset" chip.
alter table public.article_analyses
    add column if not exists source_domain text;
