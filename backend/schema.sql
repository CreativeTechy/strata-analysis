-- Strata Media - Supabase schema for the article analysis pipeline.
-- Run this in Supabase SQL Editor.

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
    add column if not exists next_run_at timestamptz,
    add column if not exists last_run_at timestamptz,
    add column if not exists last_run_status text;

alter table public.projects
    drop constraint if exists projects_repeat_interval_unit_check;
alter table public.projects
    add constraint projects_repeat_interval_unit_check
    check (repeat_interval_unit is null or repeat_interval_unit in ('minutes', 'hours', 'days'));

create table if not exists public.sources (
    id           bigint generated always as identity primary key,
    url          text not null unique,
    name         text,
    enabled      boolean not null default true,
    source_type  text not null default 'rss',
    category     text,
    limited      boolean not null default false,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now()
);

alter table public.sources
    add column if not exists limited boolean not null default false;

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
    add column if not exists embedded_at timestamptz;

create table if not exists public.users (
    id           bigint generated always as identity primary key,
    username     text not null unique,
    email        text unique,
    password_hash text not null,
    role         text not null default 'viewer',
    status       text not null default 'active',
    last_login_at timestamptz,
    created_at   timestamptz default now(),
    updated_at   timestamptz default now()
);

alter table public.users
    drop constraint if exists users_role_check;
alter table public.users
    add constraint users_role_check
    check (role in ('viewer', 'editor', 'operator', 'admin'));

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

create index if not exists articles_published_idx on public.articles (published desc);
create index if not exists articles_sentiment_idx on public.articles (sentiment);
create index if not exists articles_article_category_idx on public.articles (article_category);
create index if not exists articles_analyzed_at_idx on public.articles (analyzed_at desc);

create index if not exists project_sources_project_idx on public.project_sources (project_id);
create index if not exists project_sources_source_idx on public.project_sources (source_id);

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

alter table public.projects enable row level security;
alter table public.sources enable row level security;
alter table public.pipeline_runs enable row level security;
alter table public.articles enable row level security;
alter table public.project_sources enable row level security;
alter table public.article_projects enable row level security;

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
