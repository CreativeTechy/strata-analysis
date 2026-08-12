-- Count of scraped articles per source that were already in the DB with a
-- successful analysis under the current PIPELINE_VERSION, so enrichment
-- (LLM + embedding calls) was skipped and the existing analysis was reused
-- instead. See services/articles/enrich.py's SKIP_EXISTING_ARTICLES path.
alter table public.pipeline_run_sources
    add column if not exists skipped_existing integer not null default 0;
