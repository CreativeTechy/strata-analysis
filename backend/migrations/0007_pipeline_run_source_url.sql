-- The per-source breakdown (pipeline_run_sources) only ever recorded a
-- source's display name, which is sometimes just its bare domain (e.g.
-- "x.com") rather than the actual configured page/feed URL. Add source_url
-- so the dashboard can link out to the real address instead of showing a
-- name-only cell. Populated from the fetch diagnostics the spider already
-- writes per source - see services/pipeline/source_diagnostics.py.
alter table public.pipeline_run_sources
    add column if not exists source_url text;
