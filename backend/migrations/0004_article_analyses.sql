-- Per-run analysis snapshots, so an analysis run is an independent thing you
-- can compare against another run rather than an alias for "the latest
-- analysis".
--
-- The problem this fixes
-- ----------------------
-- Analysis output lives on the `articles` row (one set of columns per
-- article), and `articles.pipeline_run_id` records which run *first* saved the
-- article and is deliberately never re-attributed (services/articles/store.py).
-- Both behaviours were correct in the crawler this was forked from, where a run
-- *discovered* articles: "which run first saved this" partitioned runs cleanly
-- and each article was analyzed once, at discovery.
--
-- Here there is no discovery - a run re-analyzes articles that already exist -
-- so the same two behaviours combine into: the second run over a project tags
-- zero articles (its dashboard is empty) while its results overwrite the first
-- run's on the shared article row (the first run's dashboard retroactively
-- shows the second run's numbers). Runs were not comparable because nothing
-- stored what any run other than the most recent one actually concluded.
--
-- The shape
-- ---------
-- One row per (run_id, article_id) holding that run's analysis output only.
-- Article-intrinsic fields (url, title, text, published, verified, source) are
-- NOT copied - a reader joins back to `articles` for those, so an edited title
-- or a corrected publish date stays corrected everywhere instead of being
-- frozen into every historical snapshot.
--
-- Embeddings are likewise excluded: an embedding is a property of the article's
-- text, not of the run that happened to compute it, and embedding_json is by
-- far the widest column here - snapshotting it per run would multiply the
-- table's size for a value that never differs between runs of the same text.
--
-- `articles` keeps the latest analysis exactly as it does today, so every
-- non-run-scoped reader (the Articles page, JSONL export, keyword search, the
-- Intelligence Copilot) is untouched by this migration.
create table if not exists public.article_analyses (
    run_id                     text   not null references public.pipeline_runs(id) on delete cascade,
    article_id                 bigint not null references public.articles(id)      on delete cascade,

    summary                    text,
    sentiment                  text,
    sentiment_score            numeric,
    sentiment_low_confidence   boolean not null default false,
    sentiment_model            text,
    relevance_score            numeric,
    category                   text,
    article_category           text,
    category_confidence        numeric,
    writer_tone                text,
    writer_tone_confidence     numeric,
    article_tone               text,
    article_tone_confidence    numeric,
    classification_model       text,

    insight_json               jsonb  not null default '{}'::jsonb,
    organizations              jsonb  not null default '[]'::jsonb,
    entities                   jsonb  not null default '[]'::jsonb,
    topics                     jsonb  not null default '[]'::jsonb,
    key_points                 jsonb  not null default '[]'::jsonb,
    risks                      jsonb  not null default '[]'::jsonb,
    opportunities              jsonb  not null default '[]'::jsonb,
    brands                     jsonb  not null default '[]'::jsonb,
    car_models                 jsonb  not null default '[]'::jsonb,
    -- The normalized child tables (article_people_opinions, article_tags,
    -- article_feedback_items) are wiped and rewritten on every analysis, so
    -- they only ever hold the latest run's view. Keeping the run's opinions
    -- here as JSON preserves the demographic breakdown per run without
    -- versioning three more tables.
    people_opinions            jsonb  not null default '[]'::jsonb,
    extraction_model           text,

    gender                     text   not null default 'unknown',
    age_range                  text   not null default 'unknown',
    region                     text   not null default 'unknown',
    segment                    text   not null default 'unknown',

    source_language            text,
    source_language_confidence numeric,

    analysis_model             text,
    analysis_prompt_version    text,
    analysis_pipeline_version  text,
    analysis_status            text   not null default 'pending',
    analysis_error             text,
    analyzed_at                timestamp with time zone,

    created_at                 timestamp with time zone not null default now(),

    primary key (run_id, article_id)
);

-- run_id alone is served by the primary key's leading column; this is the other
-- direction - "every run that has analyzed this article", which is what a
-- per-article history view reads.
create index if not exists article_analyses_article_idx
    on public.article_analyses (article_id);

-- The dashboard's per-run sentiment comparison groups by (run_id, sentiment)
-- across a project's articles.
create index if not exists article_analyses_run_sentiment_idx
    on public.article_analyses (run_id, sentiment);


-- Deleting a run is its own permission: pipeline.stop is "halt something in
-- flight" and is safe, whereas removing a run discards a comparison point the
-- dashboard's history charts are drawn from.
insert into public.permissions (key, description) values
    ('pipeline.delete', 'Delete an analysis run and its recorded results')
on conflict (key) do nothing;

-- 'admin' is absent by design here as in schema.sql: full_access already
-- grants everything. 'operator' is the role that runs and stops analysis, so
-- it is the one that cleans up after itself.
insert into public.role_permissions (role_id, permission_id)
select r.id, p.id
from (values
    ('operator', 'pipeline.delete')
) as seed(role_name, perm_key)
join public.roles r        on r.name = seed.role_name
join public.permissions p  on p.key  = seed.perm_key
on conflict do nothing;
