-- Strata - Postgres schema for the document analysis pipeline.
--
-- This file is the whole schema. It is applied as migration `0001_baseline` by
-- backend/migrate.py, and is also mounted into docker-entrypoint-initdb.d so a
-- fresh volume starts from it.
--
-- Every statement is idempotent (`if not exists` / `or replace` /
-- `drop ... if exists` before create / `on conflict do nothing`), which is what
-- lets migrate.py re-apply the baseline whenever its checksum changes. Keep it
-- that way: a statement that fails on second run breaks the runner.
--
-- Conventions
-- -----------
-- * Surrogate keys are `bigint generated always as identity`.
-- * Join tables use a composite primary key of their two FKs, no surrogate id.
-- * `created_at`/`updated_at` are always `timestamptz not null default now()`.
--   `updated_at` is maintained by the set_updated_at() trigger, never by hand,
--   on every table that has the column.
-- * A child row dies with its parent (`on delete cascade`); a reference that is
--   merely provenance goes null instead (`on delete set null`), so losing a run
--   or a story group never deletes articles.
-- * Constraints are named explicitly rather than left to Postgres, so the name
--   is stable and a later `drop constraint if exists` can find it.
-- * Every foreign key has an index that can serve it (leading column of a
--   composite index counts), so deleting a parent never seq-scans the child.
--
-- Sections
-- --------
--   1. Shared helpers
--   2. Identity and access control
--   3. Projects
--   4. Analysis runs
--   5. Articles
--   6. Per-article analysis output
--   7. Cross-article idea clusters
--   8. Uploaded documents
--   9. Competitor study
--  10. Seed data

-- =============================================================================
-- 1. Shared helpers
-- =============================================================================

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

-- =============================================================================
-- 2. Identity and access control
--
-- A role is a named, editable set of permissions. `is_system` protects the
-- seeded 'admin' role from deletion; `full_access` grants every permission
-- automatically (also only seeded on 'admin') so the app always keeps one role
-- that cannot be locked out of itself.
-- =============================================================================

create table if not exists public.roles (
    id           bigint generated always as identity primary key,
    name         text not null unique,
    description  text,
    is_system    boolean not null default false,
    full_access  boolean not null default false,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create table if not exists public.permissions (
    id          bigint generated always as identity primary key,
    key         text not null unique,
    description text
);

create table if not exists public.role_permissions (
    role_id       bigint not null references public.roles(id) on delete cascade,
    permission_id bigint not null references public.permissions(id) on delete cascade,
    primary key (role_id, permission_id)
);

create index if not exists role_permissions_permission_idx
    on public.role_permissions (permission_id);

-- users.role_id deliberately has no `on delete` action: a role that is still
-- assigned to somebody must not be deletable, and the FK is what enforces it.
create table if not exists public.users (
    id            bigint generated always as identity primary key,
    username      text not null unique,
    email         text unique,
    password_hash text not null,
    role_id       bigint not null references public.roles(id),
    status        text not null default 'active',
    last_login_at timestamptz,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    constraint users_status_check check (status in ('active', 'disabled'))
);

create index if not exists users_role_id_idx on public.users (role_id);

create table if not exists public.sessions (
    token_hash   text primary key,
    user_id      bigint not null references public.users(id) on delete cascade,
    csrf_token   text not null,
    created_at   timestamptz not null default now(),
    last_seen_at timestamptz default now(),
    expires_at   timestamptz not null
);

create index if not exists sessions_user_idx on public.sessions (user_id);
create index if not exists sessions_expires_idx on public.sessions (expires_at);

drop trigger if exists set_roles_updated_at on public.roles;
create trigger set_roles_updated_at
before update on public.roles
for each row
execute function public.set_updated_at();

drop trigger if exists set_users_updated_at on public.users;
create trigger set_users_updated_at
before update on public.users
for each row
execute function public.set_updated_at();

-- =============================================================================
-- 3. Projects
--
-- `mode` picks which product surface a project is: 'sentiment' is the opinion
-- monitor, 'competitor' is the competitor study.
-- =============================================================================

create table if not exists public.projects (
    id               bigint generated always as identity primary key,
    name             text not null,
    status           text not null default 'draft',
    mode             text not null default 'sentiment',
    description      text,
    location         text,
    location_type    text,
    target_audience  text,
    hashtags         jsonb default '[]'::jsonb,
    keywords         jsonb default '[]'::jsonb,
    usernames        jsonb default '[]'::jsonb,
    start_date       date,
    end_date         date,
    embedding_json   jsonb default '[]'::jsonb,
    embedding_model  text,
    embedding_source text,
    embedded_at      timestamptz,
    last_run_at      timestamptz,
    last_run_status  text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    constraint projects_location_type_check
        check (location_type is null
               or location_type in ('on_site', 'remote', 'hybrid')),
    constraint projects_mode_check check (mode in ('sentiment', 'competitor'))
);

create index if not exists projects_status_idx on public.projects (status);
create index if not exists projects_mode_idx on public.projects (mode);
create index if not exists projects_created_idx on public.projects (created_at desc);

drop trigger if exists set_projects_updated_at on public.projects;
create trigger set_projects_updated_at
before update on public.projects
for each row
execute function public.set_updated_at();

-- Which dashboard users can see a project. Every full_access ("admin") user is
-- linked to every project: new projects get this from
-- projects_store.create_project(), and the backfill in section 10 covers rows
-- that predate the link.
create table if not exists public.project_users (
    project_id bigint not null references public.projects(id) on delete cascade,
    user_id    bigint not null references public.users(id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (project_id, user_id)
);

create index if not exists project_users_project_idx on public.project_users (project_id);
create index if not exists project_users_user_idx on public.project_users (user_id);

-- =============================================================================
-- 4. Analysis runs
--
-- One row per analysis run: the AI stage pipeline re-run over the articles a
-- project already holds. `pipeline` is 'analysis' for those and
-- 'competitor-analysis' for a competitor study's finding generation.
-- =============================================================================

create table if not exists public.pipeline_runs (
    id                   text primary key,
    pipeline             text not null default 'analysis',
    status               text not null default 'queued',
    stage                text not null default 'queued',
    message              text,
    articles_selected    integer not null default 0,
    articles_analyzed    integer not null default 0,
    articles_failed      integer not null default 0,
    error                text,
    project_id           bigint references public.projects(id) on delete set null,
    started_at           timestamptz default now(),
    finished_at          timestamptz,
    cancel_requested_at  timestamptz,
    cancelled_at         timestamptz,
    has_detail           boolean not null default true,
    prepare_started_at   timestamptz,
    prepare_finished_at  timestamptz,
    analysis_started_at  timestamptz,
    analysis_finished_at timestamptz,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now()
);

create index if not exists pipeline_runs_created_idx on public.pipeline_runs (created_at desc);
create index if not exists pipeline_runs_status_idx on public.pipeline_runs (status);
create index if not exists pipeline_runs_project_idx on public.pipeline_runs (project_id);

-- Per-document breakdown for a single run. A document is this product's unit of
-- provenance, so it answers the same question the crawler's per-source
-- breakdown used to: which input contributed what, and what failed on it.
-- Articles that reached the project some other way (a JSONL import) share one
-- 'Imported articles' row, hence the text key rather than a document_id FK -
-- `document_id` is a hint for the dashboard to link on, not a constraint, and
-- is deliberately unconstrained because it may point at either document table.
create table if not exists public.pipeline_run_documents (
    run_id      text not null references public.pipeline_runs(id) on delete cascade,
    document    text not null,
    document_id bigint,
    selected    integer not null default 0,
    analyzed    integer not null default 0,
    failed      integer not null default 0,
    note        text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    primary key (run_id, document)
);

create index if not exists pipeline_run_documents_run_idx
    on public.pipeline_run_documents (run_id);

drop trigger if exists set_pipeline_runs_updated_at on public.pipeline_runs;
create trigger set_pipeline_runs_updated_at
before update on public.pipeline_runs
for each row
execute function public.set_updated_at();

drop trigger if exists set_pipeline_run_documents_updated_at on public.pipeline_run_documents;
create trigger set_pipeline_run_documents_updated_at
before update on public.pipeline_run_documents
for each row
execute function public.set_updated_at();

-- =============================================================================
-- 5. Articles
--
-- `url` is the unique key. For an article split out of an uploaded document,
-- `source` is the document's filename and `source_url` is
-- `document://<kind>/<document_id>`, so every article from one file groups
-- under it while `url` stays per-article.
--
-- Provenance vs. parsed time: `published` is the raw string the input carried;
-- `published_at` is the parsed value and `published_precision` records how much
-- of it the input actually gave us, so trend math can exclude rows it cannot
-- place in time.
--   exact   - carried a time
--   day     - carried a calendar date only
--   unknown - nothing usable; published_at stays null
--
-- The flat jsonb list columns (organizations, entities, topics, ...) and
-- insight_json are the authoritative shape for articles_store.py and the
-- dashboard. Section 6's child tables hold the same data normalized, for
-- queries the jsonb shape cannot serve; store.py writes both.
-- =============================================================================

create table if not exists public.articles (
    id                        bigint generated always as identity primary key,
    url                       text not null unique,
    source                    text,
    source_url                text,
    title                     text,
    author                    text,
    published                 text,
    published_at              timestamptz,
    published_precision       text,
    text                      text,
    fetched_at                timestamptz,
    verified                  boolean not null default false,

    -- Change detection for a re-uploaded/re-imported body.
    content_hash              text,
    content_changed_at        timestamptz default now(),

    -- Syndication collapse. Null until dedup.py assigns a group.
    story_id                  bigint,

    -- Which analysis run last touched this row.
    pipeline_run_id           text references public.pipeline_runs(id) on delete set null,

    -- Stage output: summary and sentiment.
    summary                   text,
    sentiment                 text,
    sentiment_score           numeric,
    sentiment_low_confidence  boolean not null default false,
    sentiment_model           text,
    relevance_score           numeric,

    -- Stage output: classification.
    category                  text,
    article_category          text,
    category_confidence       numeric,
    writer_tone               text,
    writer_tone_confidence    numeric,
    article_tone              text,
    article_tone_confidence   numeric,
    classification_model      text,

    -- Stage output: structured extraction and entities.
    insight_json              jsonb default '{}'::jsonb,
    organizations             jsonb default '[]'::jsonb,
    entities                  jsonb default '[]'::jsonb,
    topics                    jsonb default '[]'::jsonb,
    key_points                jsonb default '[]'::jsonb,
    risks                     jsonb default '[]'::jsonb,
    opportunities             jsonb default '[]'::jsonb,
    brands                    jsonb default '[]'::jsonb,
    car_models                jsonb default '[]'::jsonb,
    extraction_model          text,

    -- Stage output: the speaker's demographic segment, as a rollup of the
    -- per-opinion values in article_people_opinions.
    gender                    text not null default 'unknown',
    age_range                 text not null default 'unknown',
    region                    text not null default 'unknown',
    segment                   text not null default 'unknown',

    -- Stage output: language.
    source_language           text,
    source_language_confidence numeric,

    -- Embedding.
    embedding_json            jsonb default '[]'::jsonb,
    embedding_model           text,
    embedding_source          text,
    embedding_dimensions      integer,
    embedded_at               timestamptz,

    -- Run bookkeeping. `analysis_status` starts at 'success' rather than
    -- 'pending' so a row imported with a full analysis attached is not
    -- re-queued; 'failed'/'pending'/'processing' mean the pipeline has actually
    -- seen the row.
    analysis_model            text,
    analysis_prompt_version   text,
    analysis_pipeline_version text,
    analysis_status           text not null default 'success',
    analysis_error            text,
    analysis_started_at       timestamptz,
    analysis_finished_at      timestamptz,
    analysis_attempt_count    integer not null default 0,
    analyzed_at               timestamptz,
    reprocess_requested_at    timestamptz,

    created_at                timestamptz not null default now(),

    constraint articles_published_precision_check
        check (published_precision is null
               or published_precision in ('exact', 'day', 'unknown')),
    constraint articles_analysis_status_check
        check (analysis_status in ('pending', 'processing', 'success', 'failed', 'partial'))
);

-- Syndication collapse: group near-identical article bodies into one story.
--
-- Prevalence must be counted per independent story, not per URL. One wire story
-- republished on 30 sites is one story that 30 outlets carried; counting it as
-- 30 independent sources inflates every number in the product.
--
-- `signature` is a 128-permutation MinHash sketch (see backend/dedup.py); the
-- fraction of agreeing positions estimates Jaccard similarity over the body's
-- 4-word shingles. `band_keys` are 16 LSH band hashes: two bodies sharing any
-- band key are candidate duplicates, which turns lookup into one indexed array
-- overlap instead of a scan. MinHash rather than SimHash because a fixed
-- Hamming threshold is not scale invariant across article lengths - see the
-- module docstring for the measured failure that motivated it.
--
-- Both are null for a *singleton* group: an article whose body is too short to
-- profile meaningfully. Such an article is still an independent story - we
-- simply cannot prove it duplicates anything - so it gets its own group rather
-- than being left unassigned. A null band_keys never overlaps, so singletons are
-- naturally excluded from duplicate matching, and downstream counting stays
-- uniform (`count(distinct story_id)`) with no nulls to special-case.
create table if not exists public.story_groups (
    id                   bigint generated always as identity primary key,
    project_id           bigint references public.projects(id) on delete cascade,
    canonical_article_id bigint references public.articles(id) on delete set null,
    signature            integer[],
    band_keys            bigint[],
    member_count         integer not null default 1,
    first_seen_at        timestamptz not null default now(),
    last_seen_at         timestamptz not null default now(),
    created_at           timestamptz not null default now(),
    constraint story_groups_signature_pairing
        check ((signature is null) = (band_keys is null))
);

create index if not exists story_groups_band_keys_idx
    on public.story_groups using gin (band_keys);
create index if not exists story_groups_project_idx on public.story_groups (project_id);
create index if not exists story_groups_canonical_article_idx
    on public.story_groups (canonical_article_id);

-- articles.story_id -> story_groups is a cycle with
-- story_groups.canonical_article_id -> articles, so one side has to be added
-- after both tables exist.
alter table public.articles
    drop constraint if exists articles_story_id_fkey;
alter table public.articles
    add constraint articles_story_id_fkey
    foreign key (story_id) references public.story_groups(id) on delete set null;

create index if not exists articles_published_idx on public.articles (published desc);
create index if not exists articles_published_at_idx
    on public.articles (published_at desc) where published_at is not null;
create index if not exists articles_fetched_at_idx on public.articles (fetched_at desc);
create index if not exists articles_analyzed_at_idx on public.articles (analyzed_at desc);
create index if not exists articles_content_changed_idx on public.articles (content_changed_at);
create index if not exists articles_sentiment_idx on public.articles (sentiment);
create index if not exists articles_article_category_idx on public.articles (article_category);
create index if not exists articles_source_language_idx on public.articles (source_language);
create index if not exists articles_analysis_status_idx on public.articles (analysis_status);
create index if not exists articles_pipeline_run_id_idx on public.articles (pipeline_run_id);
create index if not exists articles_story_idx on public.articles (story_id);
create index if not exists articles_verified_idx on public.articles (verified);
create index if not exists articles_gender_idx on public.articles (gender);
create index if not exists articles_age_range_idx on public.articles (age_range);
create index if not exists articles_region_idx on public.articles (region);
create index if not exists articles_segment_idx on public.articles (segment);

-- Worklist indexes: each one is exactly the set of rows a backfill still has to
-- visit, so the pass stays resumable and cheap as the table grows.
create index if not exists articles_published_unparsed_idx
    on public.articles (id) where published_precision is null;
create index if not exists articles_story_unassigned_idx
    on public.articles (id) where story_id is null;
create index if not exists articles_reprocess_requested_idx
    on public.articles (reprocess_requested_at) where reprocess_requested_at is not null;

-- Which projects an article belongs to. `similarity_score` is how well it
-- matched the project when it was linked.
create table if not exists public.article_projects (
    article_id       bigint not null references public.articles(id) on delete cascade,
    project_id       bigint not null references public.projects(id) on delete cascade,
    similarity_score numeric,
    created_at       timestamptz not null default now(),
    primary key (article_id, project_id)
);

create index if not exists article_projects_project_idx on public.article_projects (project_id);
create index if not exists article_projects_article_idx on public.article_projects (article_id);
create index if not exists article_projects_similarity_idx
    on public.article_projects (similarity_score desc);

-- =============================================================================
-- 6. Per-article analysis output
--
-- Rows here are fully replaced (delete + insert) each time an article is
-- (re)analyzed - see store.py's _replace_article_children() - so reprocessing
-- an article never leaves stale rows behind.
-- =============================================================================

create table if not exists public.article_feedback_items (
    id            bigint generated always as identity primary key,
    article_id    bigint not null references public.articles(id) on delete cascade,
    feedback_type text not null,
    text          text not null,
    created_at    timestamptz not null default now()
);

create index if not exists article_feedback_items_article_idx
    on public.article_feedback_items (article_id);
create index if not exists article_feedback_items_type_idx
    on public.article_feedback_items (feedback_type);

-- One opinion voiced in the article, with who voiced it. `segment_raw` is what
-- the model said; `segment` is that mapped onto segment_taxonomy.
create table if not exists public.article_people_opinions (
    id          bigint generated always as identity primary key,
    article_id  bigint not null references public.articles(id) on delete cascade,
    opinion     text not null,
    sentiment   text not null default 'neutral',
    category    text not null default '',
    gender      text not null default 'unknown',
    age_range   text not null default 'unknown',
    region      text not null default 'unknown',
    segment_raw text not null default 'unknown',
    segment     text not null default 'unknown',
    created_at  timestamptz not null default now()
);

create index if not exists article_people_opinions_article_idx
    on public.article_people_opinions (article_id);

create table if not exists public.article_tags (
    id         bigint generated always as identity primary key,
    article_id bigint not null references public.articles(id) on delete cascade,
    tag_type   text not null,
    value      text not null,
    created_at timestamptz not null default now(),
    constraint article_tags_tag_type_check
        check (tag_type in ('organization', 'entity', 'topic'))
);

create index if not exists article_tags_article_idx on public.article_tags (article_id);
create index if not exists article_tags_type_value_idx on public.article_tags (tag_type, value);

-- The canonical set of demographic segments `article_people_opinions.segment`
-- resolves to. Embedded so a new raw label can attach by similarity instead of
-- spawning a near-duplicate.
create table if not exists public.segment_taxonomy (
    id               bigint generated always as identity primary key,
    canonical_label  text not null unique,
    embedding_json   jsonb default '[]'::jsonb,
    embedding_model  text,
    embedding_source text,
    embedded_at      timestamptz,
    first_seen_at    timestamptz default now(),
    last_seen_at     timestamptz default now()
);

-- =============================================================================
-- 7. Cross-article idea clusters
--
-- A project-scoped rollup of frequent_ideas that accumulates across analysis
-- runs, unlike analysis/aggregation.py's build_topic_insight() which only ever
-- sees one run's in-memory batch. Clustering is exact-match on (project,
-- normalized idea text, type, category) - the same dedupe key
-- build_topic_insight() already uses for a single run, just persisted so it
-- compounds over time instead of resetting every run. The embedding lets a new
-- idea that does not exact-match still attach by cosine similarity rather than
-- spawning a near-duplicate cluster; see _replace_idea_clusters_for_article().
-- =============================================================================

create table if not exists public.idea_clusters (
    id                 bigint generated always as identity primary key,
    project_id         bigint not null references public.projects(id) on delete cascade,
    idea               text not null,
    normalized_idea    text generated always as (lower(trim(idea))) stored,
    type               text not null default 'issue',
    category           text not null default '',
    frequency_estimate integer not null default 0,
    embedding_json     jsonb default '[]'::jsonb,
    embedding_model    text,
    embedding_source   text,
    embedded_at        timestamptz,
    first_seen_at      timestamptz default now(),
    last_seen_at       timestamptz default now(),
    updated_at         timestamptz not null default now(),
    constraint idea_clusters_type_check
        check (type in ('complaint', 'praise', 'suggestion', 'issue')),
    constraint idea_clusters_unique_key
        unique (project_id, normalized_idea, type, category)
);

create index if not exists idea_clusters_project_idx on public.idea_clusters (project_id);
create index if not exists idea_clusters_frequency_idx
    on public.idea_clusters (frequency_estimate desc);

drop trigger if exists set_idea_clusters_updated_at on public.idea_clusters;
create trigger set_idea_clusters_updated_at
before update on public.idea_clusters
for each row
execute function public.set_updated_at();

-- Which articles contributed to a cluster. frequency_estimate is recomputed
-- from this table's row count on every write (see store.py), so reprocessing an
-- article can never double-count it.
create table if not exists public.idea_cluster_articles (
    idea_cluster_id bigint not null references public.idea_clusters(id) on delete cascade,
    article_id      bigint not null references public.articles(id) on delete cascade,
    created_at      timestamptz not null default now(),
    primary key (idea_cluster_id, article_id)
);

create index if not exists idea_cluster_articles_article_idx
    on public.idea_cluster_articles (article_id);

-- =============================================================================
-- 8. Uploaded documents
--
-- Two parallel trees, one per product surface: `project_*` for the opinion
-- monitor, `competitor_*` for a competitor study. Same shape, different
-- consumers - see project_documents_store.py and competitor_documents_store.py.
--
-- Flow: upload -> extract text (text layer, or OCR where there is none) ->
-- LLM-split into candidate articles -> operator approves -> materialize into
-- `articles`. `status` tracks extraction, `articles_status` tracks the split.
-- Large files are extracted per chunk so a partial failure is recoverable and
-- `processed_chunks`/`total_chunks` can drive a progress bar.
-- =============================================================================

create table if not exists public.project_documents (
    id                bigint generated always as identity primary key,
    project_id        bigint not null references public.projects(id) on delete cascade,
    original_filename text not null,
    storage_path      text not null,
    mime_type         text,
    size_bytes        bigint not null default 0,
    status            text not null default 'uploaded',
    extracted_text    text,
    extraction_method text,
    extraction_error  text,
    extracted_at      timestamptz,
    total_chunks      integer,
    processed_chunks  integer not null default 0,
    articles_status   text not null default 'pending',
    articles_error    text,
    created_at        timestamptz not null default now(),
    constraint project_documents_status_check
        check (status in ('uploaded', 'processing', 'processed', 'failed')),
    constraint project_documents_extraction_method_check
        check (extraction_method is null
               or extraction_method in ('text', 'ocr', 'mixed')),
    constraint project_documents_articles_status_check
        check (articles_status in ('pending', 'generating', 'ready', 'failed', 'skipped'))
);

create index if not exists project_documents_project_idx
    on public.project_documents (project_id, created_at desc);

create table if not exists public.project_document_chunks (
    id          bigint generated always as identity primary key,
    document_id bigint not null references public.project_documents(id) on delete cascade,
    chunk_index integer not null,
    text        text,
    method      text,
    error       text,
    created_at  timestamptz not null default now(),
    constraint project_document_chunks_method_check
        check (method is null or method in ('text', 'ocr'))
);

create unique index if not exists project_document_chunks_key
    on public.project_document_chunks (document_id, chunk_index);
create index if not exists project_document_chunks_document_idx
    on public.project_document_chunks (document_id);

-- A candidate article the LLM split out of a document, awaiting review.
-- `article_id` is set once approval materializes it into `articles`; it goes
-- null rather than cascading if that article is later deleted, so the candidate
-- and its review history survive.
create table if not exists public.project_document_articles (
    id          bigint generated always as identity primary key,
    document_id bigint not null references public.project_documents(id) on delete cascade,
    project_id  bigint not null references public.projects(id) on delete cascade,
    title       text not null,
    summary     text,
    body        text not null,
    status      text not null default 'pending',
    article_id  bigint references public.articles(id) on delete set null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    constraint project_document_articles_status_check
        check (status in ('pending', 'approved', 'rejected'))
);

create index if not exists project_document_articles_document_idx
    on public.project_document_articles (document_id);
create index if not exists project_document_articles_project_idx
    on public.project_document_articles (project_id, status);
create index if not exists project_document_articles_article_idx
    on public.project_document_articles (article_id);

drop trigger if exists set_project_document_articles_updated_at on public.project_document_articles;
create trigger set_project_document_articles_updated_at
before update on public.project_document_articles
for each row
execute function public.set_updated_at();

create table if not exists public.competitor_documents (
    id                bigint generated always as identity primary key,
    project_id        bigint not null references public.projects(id) on delete cascade,
    original_filename text not null,
    storage_path      text not null,
    mime_type         text,
    size_bytes        bigint not null default 0,
    status            text not null default 'uploaded',
    extracted_text    text,
    extraction_method text,
    extraction_error  text,
    extracted_at      timestamptz,
    total_chunks      integer,
    processed_chunks  integer not null default 0,
    articles_status   text not null default 'pending',
    articles_error    text,
    created_at        timestamptz not null default now(),
    constraint competitor_documents_status_check
        check (status in ('uploaded', 'processing', 'processed', 'failed')),
    constraint competitor_documents_extraction_method_check
        check (extraction_method is null
               or extraction_method in ('text', 'ocr', 'mixed')),
    constraint competitor_documents_articles_status_check
        check (articles_status in ('pending', 'generating', 'ready', 'failed', 'skipped'))
);

create index if not exists competitor_documents_project_idx
    on public.competitor_documents (project_id, created_at desc);

create table if not exists public.competitor_document_chunks (
    id          bigint generated always as identity primary key,
    document_id bigint not null references public.competitor_documents(id) on delete cascade,
    chunk_index integer not null,
    text        text,
    method      text,
    error       text,
    created_at  timestamptz not null default now(),
    constraint competitor_document_chunks_method_check
        check (method is null or method in ('text', 'ocr'))
);

create unique index if not exists competitor_document_chunks_key
    on public.competitor_document_chunks (document_id, chunk_index);
create index if not exists competitor_document_chunks_document_idx
    on public.competitor_document_chunks (document_id);

create table if not exists public.competitor_document_articles (
    id          bigint generated always as identity primary key,
    document_id bigint not null references public.competitor_documents(id) on delete cascade,
    project_id  bigint not null references public.projects(id) on delete cascade,
    title       text not null,
    summary     text,
    body        text not null,
    status      text not null default 'pending',
    article_id  bigint references public.articles(id) on delete set null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    constraint competitor_document_articles_status_check
        check (status in ('pending', 'approved', 'rejected'))
);

create index if not exists competitor_document_articles_document_idx
    on public.competitor_document_articles (document_id);
create index if not exists competitor_document_articles_project_idx
    on public.competitor_document_articles (project_id, status);
create index if not exists competitor_document_articles_article_idx
    on public.competitor_document_articles (article_id);

drop trigger if exists set_competitor_document_articles_updated_at on public.competitor_document_articles;
create trigger set_competitor_document_articles_updated_at
before update on public.competitor_document_articles
for each row
execute function public.set_updated_at();

-- =============================================================================
-- 9. Competitor study
--
-- `business_profiles` is the operator's own company, one per project.
-- `competitors` are the companies a study's approved articles turn out to be
-- about - named by document_analysis.py, not discovered, since there is no
-- online tier. `competitor_findings` is what generate_findings() produces.
-- =============================================================================

create table if not exists public.business_profiles (
    id               bigint generated always as identity primary key,
    project_id       bigint not null unique references public.projects(id) on delete cascade,
    name             text not null,
    website          text,
    description      text,
    industry         text,
    market           text,
    geography        text,
    positioning      text,
    offerings        jsonb not null default '[]'::jsonb,
    audience         jsonb not null default '[]'::jsonb,
    differentiators  jsonb not null default '[]'::jsonb,
    keywords         jsonb not null default '[]'::jsonb,
    target_countries jsonb not null default '[]'::jsonb,
    context_summary  text,
    embedding_json   jsonb default '[]'::jsonb,
    embedding_model  text,
    embedded_at      timestamptz,
    analysis_model   text,
    prompt_version   text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

drop trigger if exists set_business_profiles_updated_at on public.business_profiles;
create trigger set_business_profiles_updated_at
before update on public.business_profiles
for each row
execute function public.set_updated_at();

create table if not exists public.competitors (
    id                    bigint generated always as identity primary key,
    project_id            bigint not null references public.projects(id) on delete cascade,
    name                  text not null,
    aliases               jsonb not null default '[]'::jsonb,
    website               text,
    domain                text,
    description           text,
    country               text,
    operates_in_countries jsonb not null default '[]'::jsonb,
    size_tier             text not null default 'unknown',
    size_rank             integer,
    size_signals          jsonb not null default '{}'::jsonb,
    relevance_score       numeric,
    status                text not null default 'suggested',
    discovery_source      text not null default 'ai',
    discovery_query       text,
    embedding_json        jsonb default '[]'::jsonb,
    embedding_model       text,
    embedding_source      text,
    embedded_at           timestamptz,
    last_analyzed_at      timestamptz,
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now(),
    constraint competitors_status_check
        check (status in ('suggested', 'tracked', 'ignored')),
    constraint competitors_size_tier_check
        check (size_tier in ('enterprise', 'mid_market', 'smb', 'startup', 'unknown'))
);

-- Identity is the domain where there is one, else the lowercased name. Two
-- partial unique indexes rather than one, because a null domain must not block
-- other nameless-domain rows the way a plain unique on (project_id, domain)
-- would allow unlimited duplicates.
create unique index if not exists competitors_project_domain_key
    on public.competitors (project_id, domain) where domain is not null;
create unique index if not exists competitors_project_name_key
    on public.competitors (project_id, lower(name)) where domain is null;

create index if not exists competitors_project_idx on public.competitors (project_id);
create index if not exists competitors_rank_idx on public.competitors (project_id, size_rank);
create index if not exists competitors_status_idx on public.competitors (project_id, status);

drop trigger if exists set_competitors_updated_at on public.competitors;
create trigger set_competitors_updated_at
before update on public.competitors
for each row
execute function public.set_updated_at();

create table if not exists public.competitor_findings (
    id                bigint generated always as identity primary key,
    project_id        bigint not null references public.projects(id) on delete cascade,
    competitor_id     bigint not null references public.competitors(id) on delete cascade,
    pipeline_run_id   text references public.pipeline_runs(id) on delete set null,
    period_start      timestamptz,
    period_end        timestamptz,
    headline          text not null,
    whats_up          text not null,
    impact            text not null,
    impact_level      text not null default 'medium',
    actions           jsonb not null default '[]'::jsonb,
    signals           jsonb not null default '[]'::jsonb,
    evidence          jsonb not null default '[]'::jsonb,
    confidence        numeric,
    confidence_reason text,
    article_count     integer not null default 0,
    story_count       integer not null default 0,
    validation_status text not null default 'pending',
    validation_notes  text,
    analysis_model    text,
    prompt_version    text,
    generated_at      timestamptz not null default now(),
    created_at        timestamptz not null default now(),
    constraint competitor_findings_impact_check
        check (impact_level in ('high', 'medium', 'low')),
    constraint competitor_findings_validation_check
        check (validation_status in ('pending', 'validated', 'rejected'))
);

create index if not exists competitor_findings_project_idx
    on public.competitor_findings (project_id, generated_at desc);
create index if not exists competitor_findings_competitor_idx
    on public.competitor_findings (competitor_id, generated_at desc);
create index if not exists competitor_findings_impact_idx
    on public.competitor_findings (project_id, impact_level);
create index if not exists competitor_findings_pipeline_run_id_idx
    on public.competitor_findings (pipeline_run_id);

-- Which articles are evidence for which competitor.
create table if not exists public.competitor_articles (
    competitor_id     bigint not null references public.competitors(id) on delete cascade,
    article_id        bigint not null references public.articles(id) on delete cascade,
    match_reason      text,
    match_score       numeric,
    validation_status text not null default 'pending',
    rejected_reason   text,
    created_at        timestamptz not null default now(),
    primary key (competitor_id, article_id),
    constraint competitor_articles_validation_check
        check (validation_status in ('pending', 'valid', 'rejected'))
);

create index if not exists competitor_articles_competitor_idx
    on public.competitor_articles (competitor_id, validation_status);
create index if not exists competitor_articles_article_idx
    on public.competitor_articles (article_id);

-- =============================================================================
-- 10. Seed data
--
-- The permission catalogue, the four stock roles, and their grants. All
-- `on conflict do nothing`, so re-running never clobbers an operator's edits to
-- a role - it only fills in what is missing.
-- =============================================================================

insert into public.permissions (key, description) values
    ('projects.view', 'View projects'),
    ('projects.create', 'Create projects'),
    ('projects.update', 'Edit projects'),
    ('projects.delete', 'Delete projects'),
    ('projects.link_users', 'Manage which dashboard users are linked to a project'),
    ('articles.view', 'View articles'),
    ('articles.delete', 'Delete all stored articles'),
    ('articles.import', 'Import articles from a JSONL export'),
    ('pipeline.view', 'View analysis runs'),
    ('pipeline.run', 'Start an analysis run'),
    ('pipeline.stop', 'Stop a running analysis'),
    ('competitors.view', 'View competitor studies, competitors, and findings'),
    ('competitors.manage', 'Create and edit the business profile and competitors'),
    ('competitors.analyze', 'Run competitor discovery and generate analysis'),
    ('users.view', 'View dashboard users'),
    ('users.create', 'Create dashboard users'),
    ('users.update', 'Edit dashboard users (role/status)'),
    ('users.delete', 'Delete dashboard users'),
    ('roles.view', 'View roles and their permissions'),
    ('roles.create', 'Create new roles'),
    ('roles.update', 'Edit roles and their permission assignments'),
    ('roles.delete', 'Delete roles')
on conflict (key) do nothing;

insert into public.roles (name, description, is_system, full_access) values
    ('admin', 'Full access to every part of the app.', true, true),
    ('editor', 'Manage projects and their documents; view articles and analysis runs.', false, false),
    ('operator', 'Run and stop analysis; view, import, and clear articles.', false, false),
    ('viewer', 'Read-only access to projects, articles, and analysis runs.', false, false)
on conflict (name) do nothing;

-- 'admin' is intentionally absent: full_access = true already grants
-- everything, so listing its grants would only create a second thing to keep in
-- sync.
insert into public.role_permissions (role_id, permission_id)
select r.id, p.id
from (values
    ('editor', 'projects.view'), ('editor', 'projects.create'),
    ('editor', 'projects.update'), ('editor', 'projects.delete'),
    ('editor', 'articles.view'), ('editor', 'pipeline.view'),
    ('editor', 'competitors.view'), ('editor', 'competitors.manage'),
    ('editor', 'competitors.analyze'),

    ('operator', 'projects.view'),
    ('operator', 'articles.view'), ('operator', 'articles.delete'),
    ('operator', 'articles.import'),
    ('operator', 'pipeline.view'), ('operator', 'pipeline.run'),
    ('operator', 'pipeline.stop'),
    ('operator', 'competitors.view'), ('operator', 'competitors.analyze'),

    ('viewer', 'projects.view'), ('viewer', 'articles.view'),
    ('viewer', 'pipeline.view'), ('viewer', 'competitors.view')
) as seed(role_name, perm_key)
join public.roles r on r.name = seed.role_name
join public.permissions p on p.key = seed.perm_key
on conflict do nothing;

-- Every project must be linked to every full_access ("admin") user. New
-- projects get this from projects_store.create_project(); this backfills any
-- project or admin created before that link existed.
insert into public.project_users (project_id, user_id)
select p.id, u.id
from public.projects p
cross join public.users u
join public.roles r on r.id = u.role_id
where r.full_access = true
on conflict (project_id, user_id) do nothing;
