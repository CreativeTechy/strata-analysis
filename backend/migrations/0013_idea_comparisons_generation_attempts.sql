-- A run-scoped idea-comparisons request (main.py's
-- get_project_idea_comparisons_view) generates lazily on first view rather
-- than on every analysis run (see 0012's comment for why). But
-- idea_comparisons has no row to read back for a run whose in-scope articles
-- genuinely have fewer than two cross-source ideas - and "generated, found
-- nothing" is indistinguishable from "never generated" once the cache read
-- comes back empty, so a run with nothing to show would regenerate (and, on
-- an LLM outage, re-fail) on every single page view instead of caching that
-- outcome once. This table is that missing "we already tried" marker,
-- written only on a run scope's own generation (see
-- services/articles/idea_comparisons.py's generate_idea_comparisons), never
-- for the project-wide scope (run_id = '' there), which only regenerates on
-- an explicit request already.
create table if not exists public.idea_comparisons_generation_attempts (
    project_id   bigint not null references public.projects(id) on delete cascade,
    run_id       text not null,
    generated_at timestamptz not null default now(),
    primary key (project_id, run_id)
);
