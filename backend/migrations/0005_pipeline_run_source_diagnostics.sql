-- Per-source fetch diagnostics: which configured sources the scraper couldn't
-- reach at all this run (blocked, HTTP error, connection failure), and which
-- ones returned zero articles even though the fetch itself succeeded.
--
-- Additive to the existing pipeline_run_sources breakdown (scraped/duplicate/
-- blocked/date_filtered/kept/enriched/saved), which only ever gets a row for
-- a source once at least one of its articles reaches enrich.py - a source
-- blocked at the network level before any article existed had no row at all
-- before this. See scraper/spiders/source_rss.py (writes the diagnostics
-- side-channel file) and services/pipeline/source_diagnostics.py (reads it).
--
-- "blocked" already means something else on this table (count of articles
-- rejected by content_guard - see enrich.py's clean_articles()), hence
-- network_blocked rather than reusing that name here.
alter table public.pipeline_run_sources
    add column if not exists http_status integer,
    add column if not exists network_blocked boolean not null default false,
    add column if not exists fetch_note text;
