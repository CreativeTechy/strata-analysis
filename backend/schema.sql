-- Strata Media - Postgres schema for the article analysis pipeline.
--
-- Applied as migration `0001_baseline` by backend/migrate.py, and mounted into
-- docker-entrypoint-initdb.d so a fresh volume starts from it. Every statement
-- is idempotent, so re-running it is safe and is how an existing database
-- converges with a fresh one.

-- The RLS policies below grant to `anon` and `authenticated`, which Supabase
-- provides but vanilla Postgres does not. Without these roles the whole file
-- aborts on a fresh database (the postgres entrypoint runs initdb scripts with
-- ON_ERROR_STOP=1), which made the documented `docker compose down -v` reset
-- fail. They are created NOLOGIN and hold no grants, so they cannot connect and
-- are inert: the backend connects as the table owner via psycopg and bypasses
-- RLS entirely. Kept rather than deleted so a database restored from the
-- Supabase era keeps behaving identically.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'anon') then
        create role anon nologin;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then
        create role authenticated nologin;
    end if;
end
$$;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create table if not exists public.projects (
    id           bigint generated always as identity primary key,
    name         text not null,
    status       text not null default 'draft',
    description  text,
    location     text,
    target_audience text,
    hashtags     jsonb default '[]'::jsonb,
    keywords     jsonb default '[]'::jsonb,
    usernames    jsonb default '[]'::jsonb,
    start_date   date,
    end_date     date,
    embedding_json jsonb default '[]'::jsonb,
    embedding_model text,
    embedding_source text,
    embedded_at  timestamptz,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now()
);

alter table public.projects
    add column if not exists description text,
    add column if not exists location text,
    add column if not exists location_type text,
    add column if not exists target_audience text,
    add column if not exists hashtags jsonb default '[]'::jsonb,
    add column if not exists keywords jsonb default '[]'::jsonb,
    add column if not exists usernames jsonb default '[]'::jsonb,
    add column if not exists embedding_json jsonb default '[]'::jsonb,
    add column if not exists embedding_model text,
    add column if not exists embedding_source text,
    add column if not exists embedded_at timestamptz,
    add column if not exists repeat_enabled boolean not null default false,
    add column if not exists repeat_interval_value integer,
    add column if not exists repeat_interval_unit text,
    add column if not exists first_run_at timestamptz,
    add column if not exists repeat_weekdays jsonb default '[]'::jsonb,
    add column if not exists next_run_at timestamptz,
    add column if not exists last_run_at timestamptz,
    add column if not exists last_run_status text;

alter table public.projects
    drop constraint if exists projects_repeat_interval_unit_check;
alter table public.projects
    add constraint projects_repeat_interval_unit_check
    check (repeat_interval_unit is null or repeat_interval_unit in ('minutes', 'hours', 'days'));

alter table public.projects
    drop constraint if exists projects_location_type_check;
alter table public.projects
    add constraint projects_location_type_check
    check (location_type is null or location_type in ('on_site', 'remote', 'hybrid'));

create table if not exists public.sources (
    id           bigint generated always as identity primary key,
    url          text not null unique,
    name         text,
    enabled      boolean not null default true,
    source_type  text not null default 'rss',
    limited      boolean not null default true,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now()
);

alter table public.sources
    add column if not exists limited boolean not null default true;

alter table public.sources
    drop column if exists category;

create table if not exists public.pipeline_runs (
    id               text primary key,
    pipeline         text not null default 'scrape',
    status           text not null default 'queued',
    stage            text not null default 'queued',
    message          text,
    articles_scraped integer not null default 0,
    articles_cleaned integer not null default 0,
    articles_saved   integer not null default 0,
    crawl_pages      integer not null default 0,
    error            text,
    project_id       bigint references public.projects(id) on delete set null,
    started_at       timestamptz default now(),
    finished_at      timestamptz,
    cancel_requested_at timestamptz,
    cancelled_at     timestamptz,
    created_at       timestamptz default now(),
    updated_at       timestamptz default now()
);

alter table public.pipeline_runs
    add column if not exists cancel_requested_at timestamptz,
    add column if not exists cancelled_at timestamptz;

-- Per-stage timing + a has_detail flag are only ever populated for runs created
-- after this migration; older rows keep has_detail = false so the dashboard can
-- show a "details unavailable for legacy run" fallback instead of guessing.
alter table public.pipeline_runs
    add column if not exists has_detail boolean not null default false,
    add column if not exists scrape_started_at timestamptz,
    add column if not exists scrape_finished_at timestamptz,
    add column if not exists clean_started_at timestamptz,
    add column if not exists clean_finished_at timestamptz,
    add column if not exists enrich_started_at timestamptz,
    add column if not exists enrich_finished_at timestamptz;

-- Per-source breakdown for a single run (scraped/kept/enriched/saved counts).
-- Only written by new runs (see enrich.py); rows simply don't exist for legacy runs.
create table if not exists public.pipeline_run_sources (
    run_id         text not null references public.pipeline_runs(id) on delete cascade,
    source         text not null,
    scraped        integer not null default 0,
    duplicate      integer not null default 0,
    blocked        integer not null default 0,
    date_filtered  integer not null default 0,
    skipped_existing integer not null default 0,
    kept           integer not null default 0,
    enriched       integer not null default 0,
    saved          integer not null default 0,
    created_at     timestamptz default now(),
    updated_at     timestamptz default now(),
    primary key (run_id, source)
);

create table if not exists public.articles (
    id              bigint generated always as identity primary key,
    url             text not null unique,
    source          text,
    source_url      text,
    title           text,
    author          text,
    published       text,
    text            text,
    fetched_at      timestamptz,
    summary         text,
    sentiment       text,
    relevance_score numeric,
    category        text,
    article_category text,
    writer_tone     text,
    article_tone    text,
    insight_json    jsonb default '{}'::jsonb,
    analysis_model  text,
    analysis_prompt_version text,
    analyzed_at     timestamptz,
    organizations   jsonb default '[]'::jsonb,
    entities        jsonb default '[]'::jsonb,
    topics          jsonb default '[]'::jsonb,
    key_points      jsonb default '[]'::jsonb,
    risks           jsonb default '[]'::jsonb,
    opportunities   jsonb default '[]'::jsonb,
    brands          jsonb default '[]'::jsonb,
    car_models      jsonb default '[]'::jsonb,
    embedding_json  jsonb default '[]'::jsonb,
    embedding_model text,
    embedding_source text,
    embedded_at     timestamptz,
    created_at      timestamptz default now()
);

alter table public.articles
    add column if not exists embedding_json jsonb default '[]'::jsonb,
    add column if not exists embedding_model text,
    add column if not exists embedding_source text,
    add column if not exists embedded_at timestamptz,
    add column if not exists writer_tone text,
    add column if not exists article_tone text;

-- Dynamic roles/permissions: a role is just a named, editable set of
-- permissions. `is_system` protects the seeded 'admin' role from deletion;
-- `full_access` grants every permission automatically (also only seeded on
-- 'admin') so the app always keeps one role that can't be locked out of.
create table if not exists public.roles (
    id           bigint generated always as identity primary key,
    name         text not null unique,
    description  text,
    is_system    boolean not null default false,
    full_access  boolean not null default false,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now()
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

drop trigger if exists set_roles_updated_at on public.roles;
create trigger set_roles_updated_at
before update on public.roles
for each row
execute function public.set_updated_at();

insert into public.permissions (key, description) values
    ('projects.view', 'View projects'),
    ('projects.create', 'Create projects'),
    ('projects.update', 'Edit projects'),
    ('projects.delete', 'Delete projects'),
    ('projects.link_users', 'Manage which dashboard users are linked to a project'),
    ('sources.view', 'View sources'),
    ('sources.create', 'Create sources'),
    ('sources.update', 'Edit sources'),
    ('sources.delete', 'Delete sources'),
    ('articles.view', 'View articles'),
    ('articles.delete', 'Delete all stored articles'),
    ('articles.import', 'Import articles from a JSONL export'),
    ('pipeline.view', 'View pipeline runs'),
    ('pipeline.run', 'Trigger the scraper pipeline'),
    ('pipeline.stop', 'Stop a running pipeline'),
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
    ('editor', 'Manage projects and sources; view articles and pipeline runs.', false, false),
    ('operator', 'Run and stop the pipeline; view and clear articles.', false, false),
    ('viewer', 'Read-only access to projects, sources, articles, and pipeline runs.', false, false)
on conflict (name) do nothing;

insert into public.role_permissions (role_id, permission_id)
select r.id, p.id
from (values
    ('editor', 'projects.view'), ('editor', 'projects.create'), ('editor', 'projects.update'), ('editor', 'projects.delete'),
    ('editor', 'sources.view'), ('editor', 'sources.create'), ('editor', 'sources.update'), ('editor', 'sources.delete'),
    ('editor', 'articles.view'), ('editor', 'pipeline.view'),
    ('operator', 'projects.view'), ('operator', 'sources.view'),
    ('operator', 'articles.view'), ('operator', 'articles.delete'), ('operator', 'articles.import'),
    ('operator', 'pipeline.view'), ('operator', 'pipeline.run'), ('operator', 'pipeline.stop'),
    ('viewer', 'projects.view'), ('viewer', 'sources.view'),
    ('viewer', 'articles.view'), ('viewer', 'pipeline.view')
) as seed(role_name, perm_key)
join public.roles r on r.name = seed.role_name
join public.permissions p on p.key = seed.perm_key
on conflict do nothing;

create table if not exists public.users (
    id           bigint generated always as identity primary key,
    username     text not null unique,
    email        text unique,
    password_hash text not null,
    role_id      bigint not null references public.roles(id),
    status       text not null default 'active',
    last_login_at timestamptz,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now()
);

alter table public.users
    drop constraint if exists users_status_check;
alter table public.users
    add constraint users_status_check
    check (status in ('active', 'disabled'));

create table if not exists public.sessions (
    token_hash   text primary key,
    user_id      bigint not null references public.users(id) on delete cascade,
    csrf_token   text not null,
    created_at   timestamptz default now(),
    last_seen_at timestamptz default now(),
    expires_at   timestamptz not null
);

create index if not exists sessions_user_idx on public.sessions (user_id);
create index if not exists sessions_expires_idx on public.sessions (expires_at);

create index if not exists users_role_id_idx on public.users (role_id);
create index if not exists role_permissions_permission_idx on public.role_permissions (permission_id);

drop trigger if exists set_users_updated_at on public.users;
create trigger set_users_updated_at
before update on public.users
for each row
execute function public.set_updated_at();

-- users/sessions hold credentials: RLS is enabled with no policies, so the
-- anon/authenticated PostgREST roles get nothing. The backend talks to this
-- database directly as the table owner (psycopg), which bypasses RLS, so
-- application access is unaffected.
alter table public.users enable row level security;
alter table public.sessions enable row level security;

create table if not exists public.project_sources (
    project_id   bigint not null references public.projects(id) on delete cascade,
    source_id    bigint not null references public.sources(id) on delete cascade,
    created_at   timestamptz default now(),
    primary key (project_id, source_id)
);

create table if not exists public.project_users (
    project_id   bigint not null references public.projects(id) on delete cascade,
    user_id      bigint not null references public.users(id) on delete cascade,
    created_at   timestamptz default now(),
    primary key (project_id, user_id)
);

-- Every project must be linked to every full_access ("admin") user by
-- default. New projects get this from projects_store.create_project(); this
-- backfills any project/admin created before that link existed.
insert into public.project_users (project_id, user_id)
select p.id, u.id
from public.projects p
cross join public.users u
join public.roles r on r.id = u.role_id
where r.full_access = true
on conflict (project_id, user_id) do nothing;

create table if not exists public.article_projects (
    article_id   bigint not null references public.articles(id) on delete cascade,
    project_id   bigint not null references public.projects(id) on delete cascade,
    similarity_score numeric,
    created_at   timestamptz default now(),
    primary key (article_id, project_id)
);

create index if not exists projects_status_idx on public.projects (status);
create index if not exists projects_created_idx on public.projects (created_at desc);
create index if not exists projects_next_run_idx on public.projects (next_run_at) where repeat_enabled = true;

create index if not exists sources_enabled_idx on public.sources (enabled);
create index if not exists sources_created_idx on public.sources (created_at desc);

create index if not exists pipeline_runs_created_idx on public.pipeline_runs (created_at desc);
create index if not exists pipeline_runs_status_idx on public.pipeline_runs (status);

create index if not exists pipeline_run_sources_run_idx on public.pipeline_run_sources (run_id);

create index if not exists articles_published_idx on public.articles (published desc);
create index if not exists articles_sentiment_idx on public.articles (sentiment);
create index if not exists articles_article_category_idx on public.articles (article_category);
create index if not exists articles_analyzed_at_idx on public.articles (analyzed_at desc);
create index if not exists articles_fetched_at_idx on public.articles (fetched_at desc);

create index if not exists project_sources_project_idx on public.project_sources (project_id);
create index if not exists project_sources_source_idx on public.project_sources (source_id);

create index if not exists project_users_project_idx on public.project_users (project_id);
create index if not exists project_users_user_idx on public.project_users (user_id);

create index if not exists article_projects_project_idx on public.article_projects (project_id);
create index if not exists article_projects_article_idx on public.article_projects (article_id);
create index if not exists article_projects_similarity_idx on public.article_projects (similarity_score desc);

drop trigger if exists set_projects_updated_at on public.projects;
create trigger set_projects_updated_at
before update on public.projects
for each row
execute function public.set_updated_at();

drop trigger if exists set_sources_updated_at on public.sources;
create trigger set_sources_updated_at
before update on public.sources
for each row
execute function public.set_updated_at();

drop trigger if exists set_pipeline_runs_updated_at on public.pipeline_runs;
create trigger set_pipeline_runs_updated_at
before update on public.pipeline_runs
for each row
execute function public.set_updated_at();

drop trigger if exists set_pipeline_run_sources_updated_at on public.pipeline_run_sources;
create trigger set_pipeline_run_sources_updated_at
before update on public.pipeline_run_sources
for each row
execute function public.set_updated_at();

alter table public.projects enable row level security;
alter table public.sources enable row level security;
alter table public.pipeline_runs enable row level security;
alter table public.pipeline_run_sources enable row level security;
alter table public.articles enable row level security;
alter table public.project_sources enable row level security;
alter table public.article_projects enable row level security;
alter table public.project_users enable row level security;

drop policy if exists "Public read access" on public.projects;
create policy "Public read access"
on public.projects
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.sources;
create policy "Public read access"
on public.sources
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.pipeline_runs;
create policy "Public read access"
on public.pipeline_runs
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.pipeline_run_sources;
create policy "Public read access"
on public.pipeline_run_sources
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.articles;
create policy "Public read access"
on public.articles
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.project_sources;
create policy "Public read access"
on public.project_sources
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.article_projects;
create policy "Public read access"
on public.article_projects
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.project_users;
create policy "Public read access"
on public.project_users
for select
to anon, authenticated
using (true);

-- =============================================================================
-- Modular analysis pipeline: persistence additions (backend/analysis/).
-- Everything below is additive and safe to re-run: existing insight_json /
-- flat jsonb columns on articles are left exactly as they were and remain
-- authoritative for existing readers (articles_store.py, the dashboard) -
-- nothing here removes or renames a column those readers depend on. The
-- new columns/tables are new capability the analysis pipeline populates
-- going forward; rows written before this migration simply have them null
-- (or the stated default), which callers must treat as "unknown"/"not yet
-- migrated", not as a real neutral result.
-- =============================================================================

alter table public.articles
    add column if not exists sentiment_score numeric,
    add column if not exists sentiment_low_confidence boolean not null default false,
    add column if not exists sentiment_model text,
    add column if not exists category_confidence numeric,
    add column if not exists writer_tone_confidence numeric,
    add column if not exists article_tone_confidence numeric,
    add column if not exists classification_model text,
    add column if not exists extraction_model text,
    add column if not exists analysis_pipeline_version text,
    add column if not exists source_language text,
    add column if not exists source_language_confidence numeric,
    add column if not exists embedding_dimensions integer,
    add column if not exists analysis_status text not null default 'success',
    add column if not exists analysis_error text,
    add column if not exists analysis_started_at timestamptz,
    add column if not exists analysis_finished_at timestamptz,
    add column if not exists analysis_attempt_count integer not null default 0,
    add column if not exists reprocess_requested_at timestamptz;

-- Legacy rows (pre-dating these columns) default to analysis_status =
-- 'success' above because they *did* complete under the old single-LLM
-- pipeline - 'failed'/'pending'/'processing' are reserved for rows the new
-- pipeline has actually seen.
alter table public.articles
    drop constraint if exists articles_analysis_status_check;
alter table public.articles
    add constraint articles_analysis_status_check
    check (analysis_status in ('pending', 'processing', 'success', 'failed', 'partial'));

create index if not exists articles_analysis_status_idx on public.articles (analysis_status);
create index if not exists articles_reprocess_requested_idx on public.articles (reprocess_requested_at) where reprocess_requested_at is not null;
create index if not exists articles_source_language_idx on public.articles (source_language);

-- One-time, safe backfill: embedding_dimensions is fully derivable from the
-- vector already stored, for rows embedded before this column existed. Only
-- touches rows where it's currently null, so it's safe to re-run.
update public.articles
set embedding_dimensions = jsonb_array_length(embedding_json)
where embedding_dimensions is null
  and embedding_json is not null
  and jsonb_typeof(embedding_json) = 'array'
  and jsonb_array_length(embedding_json) > 0;

-- --- Normalized child tables for repeated per-article items -----------------
-- Additive: insight_json / the flat jsonb list columns on articles keep
-- working exactly as before for existing readers. Rows here are fully
-- replaced (delete+insert) each time an article is (re)analyzed - see
-- store.py's _replace_article_children() - so reprocessing an article never
-- leaves stale rows behind.
create table if not exists public.article_feedback_items (
    id            bigint generated always as identity primary key,
    article_id    bigint not null references public.articles(id) on delete cascade,
    feedback_type text not null,
    text          text not null,
    created_at    timestamptz default now()
);

create table if not exists public.article_people_opinions (
    id           bigint generated always as identity primary key,
    article_id   bigint not null references public.articles(id) on delete cascade,
    opinion      text not null,
    sentiment    text not null default 'neutral',
    category     text not null default '',
    created_at   timestamptz default now()
);

create table if not exists public.article_tags (
    id           bigint generated always as identity primary key,
    article_id   bigint not null references public.articles(id) on delete cascade,
    tag_type     text not null check (tag_type in ('organization', 'entity', 'topic')),
    value        text not null,
    created_at   timestamptz default now()
);

create index if not exists article_feedback_items_article_idx on public.article_feedback_items (article_id);
create index if not exists article_feedback_items_type_idx on public.article_feedback_items (feedback_type);
create index if not exists article_people_opinions_article_idx on public.article_people_opinions (article_id);
create index if not exists article_tags_article_idx on public.article_tags (article_id);
create index if not exists article_tags_type_value_idx on public.article_tags (tag_type, value);

-- --- Cross-article idea clusters ---------------------------------------------
-- A project-scoped rollup of frequent_ideas that accumulates across pipeline
-- runs, unlike analysis/aggregation.py's build_topic_insight() which only
-- ever sees one run's in-memory batch. Clustering is exact-match on
-- (project, normalized idea text, type, category) - the same dedupe key
-- build_topic_insight() already uses for a single run, just persisted so it
-- compounds over time instead of resetting every run.
create table if not exists public.idea_clusters (
    id                 bigint generated always as identity primary key,
    project_id         bigint not null references public.projects(id) on delete cascade,
    idea               text not null,
    normalized_idea    text generated always as (lower(trim(idea))) stored,
    type               text not null default 'issue' check (type in ('complaint', 'praise', 'suggestion', 'issue')),
    category           text not null default '',
    frequency_estimate integer not null default 0,
    first_seen_at      timestamptz default now(),
    last_seen_at       timestamptz default now(),
    updated_at         timestamptz default now()
);

alter table public.idea_clusters
    drop constraint if exists idea_clusters_unique_key;
alter table public.idea_clusters
    add constraint idea_clusters_unique_key
    unique (project_id, normalized_idea, type, category);

-- Which articles contributed to a cluster; frequency_estimate is recomputed
-- from this table's row count for the cluster on every write (see store.py),
-- so reprocessing an article can never double-count it.
create table if not exists public.idea_cluster_articles (
    idea_cluster_id bigint not null references public.idea_clusters(id) on delete cascade,
    article_id      bigint not null references public.articles(id) on delete cascade,
    created_at      timestamptz default now(),
    primary key (idea_cluster_id, article_id)
);

create index if not exists idea_clusters_project_idx on public.idea_clusters (project_id);
create index if not exists idea_clusters_frequency_idx on public.idea_clusters (frequency_estimate desc);
create index if not exists idea_cluster_articles_article_idx on public.idea_cluster_articles (article_id);

drop trigger if exists set_idea_clusters_updated_at on public.idea_clusters;
create trigger set_idea_clusters_updated_at
before update on public.idea_clusters
for each row
execute function public.set_updated_at();

alter table public.article_feedback_items enable row level security;
alter table public.article_people_opinions enable row level security;
alter table public.article_tags enable row level security;
alter table public.idea_clusters enable row level security;
alter table public.idea_cluster_articles enable row level security;

drop policy if exists "Public read access" on public.article_feedback_items;
create policy "Public read access"
on public.article_feedback_items
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.article_people_opinions;
create policy "Public read access"
on public.article_people_opinions
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.article_tags;
create policy "Public read access"
on public.article_tags
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.idea_clusters;
create policy "Public read access"
on public.idea_clusters
for select
to anon, authenticated
using (true);

drop policy if exists "Public read access" on public.idea_cluster_articles;
create policy "Public read access"
on public.idea_cluster_articles
for select
to anon, authenticated
using (true);
