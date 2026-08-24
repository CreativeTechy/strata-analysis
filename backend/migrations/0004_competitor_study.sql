-- Competitor study: a second, separate experience alongside sentiment/opinions.
--
-- A project declares a `mode`. Sentiment projects behave exactly as before
-- (nothing reads `mode` on that path), while competitor projects add a profile
-- of the user's own business, a competitor set named from the study's uploaded
-- documents, and the generated analysis cards.
--
-- Evidence arrives the same way it does everywhere else in this product: a
-- document is uploaded, split into articles, and matched against each
-- competitor (see migrations 0008-0011 and services/competitors/). There are no
-- competitor channels to validate and nothing to crawl.

alter table public.projects
    add column if not exists mode text not null default 'sentiment';

alter table public.projects
    drop constraint if exists projects_mode_check;
alter table public.projects
    add constraint projects_mode_check
    check (mode in ('sentiment', 'competitor'));

create index if not exists projects_mode_idx on public.projects (mode);


-- The user's own business. One per project: it is the reference point every
-- competitor and every "how does this affect us" judgement is measured against.
-- `context_summary` is the AI's structured reading of what the user typed about
-- their business, so every "how does this affect us" judgement is measured
-- against one consistent description rather than a free-text field.
create table if not exists public.business_profiles (
    id                bigint generated always as identity primary key,
    project_id        bigint not null unique references public.projects(id) on delete cascade,
    name              text not null,
    website           text,
    description       text,
    industry          text,
    market            text,
    geography         text,
    positioning       text,
    offerings         jsonb not null default '[]'::jsonb,
    audience          jsonb not null default '[]'::jsonb,
    differentiators   jsonb not null default '[]'::jsonb,
    keywords          jsonb not null default '[]'::jsonb,
    context_summary   text,
    embedding_json    jsonb default '[]'::jsonb,
    embedding_model   text,
    embedded_at       timestamptz,
    analysis_model    text,
    prompt_version    text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

drop trigger if exists set_business_profiles_updated_at on public.business_profiles;
create trigger set_business_profiles_updated_at
before update on public.business_profiles
for each row
execute function public.set_updated_at();


-- Competitors, ranked. `size_rank` is the ordering the workspace presents
-- (1 = largest); `size_signals` records what that ranking was actually based on
-- so a user can see why one competitor outranks another instead of trusting an
-- opaque number.
create table if not exists public.competitors (
    id                bigint generated always as identity primary key,
    project_id        bigint not null references public.projects(id) on delete cascade,
    name              text not null,
    website           text,
    domain            text,
    description       text,
    -- Ranking + why.
    size_tier         text not null default 'unknown',
    size_rank         integer,
    size_signals      jsonb not null default '{}'::jsonb,
    relevance_score   numeric,
    -- Lifecycle: discovered -> the user chooses what to actually track.
    status            text not null default 'suggested',
    discovery_source  text not null default 'ai',
    discovery_query   text,
    last_analyzed_at  timestamptz,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

alter table public.competitors
    drop constraint if exists competitors_status_check;
alter table public.competitors
    add constraint competitors_status_check
    check (status in ('suggested', 'tracked', 'ignored'));

alter table public.competitors
    drop constraint if exists competitors_size_tier_check;
alter table public.competitors
    add constraint competitors_size_tier_check
    check (size_tier in ('enterprise', 'mid_market', 'smb', 'startup', 'unknown'));

-- One row per competitor per project. Domain is the identity where present
-- (two discovery passes finding "Acme" and "Acme Inc." must not duplicate);
-- name is the fallback for competitors with no website yet.
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


-- The analysis cards. Each answers exactly three questions:
--   whats_up  - what the competitor is up to
--   impact    - how it affects us (judged against the business profile)
--   actions   - what we should do about it
--
-- `evidence` carries the source rows behind the card so every claim on a card
-- is one click from the article that produced it; `story_count` counts distinct
-- story_groups (see 0003) rather than URLs, so a syndicated announcement carried
-- by twenty outlets does not read as twenty separate moves.
create table if not exists public.competitor_findings (
    id                bigint generated always as identity primary key,
    project_id        bigint not null references public.projects(id) on delete cascade,
    competitor_id     bigint not null references public.competitors(id) on delete cascade,
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
    article_count     integer not null default 0,
    story_count       integer not null default 0,
    validation_status text not null default 'pending',
    validation_notes  text,
    analysis_model    text,
    prompt_version    text,
    generated_at      timestamptz not null default now(),
    created_at        timestamptz not null default now()
);

alter table public.competitor_findings
    drop constraint if exists competitor_findings_impact_check;
alter table public.competitor_findings
    add constraint competitor_findings_impact_check
    check (impact_level in ('high', 'medium', 'low'));

alter table public.competitor_findings
    drop constraint if exists competitor_findings_validation_check;
alter table public.competitor_findings
    add constraint competitor_findings_validation_check
    check (validation_status in ('pending', 'validated', 'rejected'));

create index if not exists competitor_findings_project_idx
    on public.competitor_findings (project_id, generated_at desc);
create index if not exists competitor_findings_competitor_idx
    on public.competitor_findings (competitor_id, generated_at desc);
create index if not exists competitor_findings_impact_idx
    on public.competitor_findings (project_id, impact_level);


-- Which competitor an article belongs to, and whether it survived validation.
-- Kept separate from `article_projects` because relevance to a *competitor* is a
-- different question from relevance to a project, and because the rejection
-- reason has to be inspectable: a silently dropped article and a silently
-- included irrelevant one are both how a report ends up misleading.
create table if not exists public.competitor_articles (
    competitor_id     bigint not null references public.competitors(id) on delete cascade,
    article_id        bigint not null references public.articles(id) on delete cascade,
    match_reason      text,
    match_score       numeric,
    validation_status text not null default 'pending',
    rejected_reason   text,
    created_at        timestamptz not null default now(),
    primary key (competitor_id, article_id)
);

alter table public.competitor_articles
    drop constraint if exists competitor_articles_validation_check;
alter table public.competitor_articles
    add constraint competitor_articles_validation_check
    check (validation_status in ('pending', 'valid', 'rejected'));

create index if not exists competitor_articles_competitor_idx
    on public.competitor_articles (competitor_id, validation_status);
create index if not exists competitor_articles_article_idx
    on public.competitor_articles (article_id);


-- Matches the convention the rest of the schema uses: the backend connects as
-- the table owner via psycopg and bypasses RLS; these only govern the
-- PostgREST-style anon/authenticated roles, which get read-only access.
alter table public.business_profiles enable row level security;
alter table public.competitors enable row level security;
alter table public.competitor_findings enable row level security;
alter table public.competitor_articles enable row level security;

do $$
declare
    target text;
begin
    foreach target in array array[
        'business_profiles', 'competitors',
        'competitor_findings', 'competitor_articles'
    ]
    loop
        execute format('drop policy if exists "Public read access" on public.%I', target);
        execute format(
            'create policy "Public read access" on public.%I for select to anon, authenticated using (true)',
            target
        );
    end loop;
end
$$;


-- Permissions for the new experience, following the existing key convention.
insert into public.permissions (key, description) values
    ('competitors.view', 'View competitor studies, competitors, and findings'),
    ('competitors.manage', 'Create and edit the business profile and competitors'),
    ('competitors.analyze', 'Run competitor discovery and generate analysis')
on conflict (key) do nothing;

-- Admin has full_access so it needs no explicit grant. Editors manage, viewers read.
insert into public.role_permissions (role_id, permission_id)
select r.id, p.id
from (values
    ('editor', 'competitors.view'), ('editor', 'competitors.manage'), ('editor', 'competitors.analyze'),
    ('operator', 'competitors.view'), ('operator', 'competitors.analyze'),
    ('viewer', 'competitors.view')
) as seed(role_name, perm_key)
join public.roles r on r.name = seed.role_name
join public.permissions p on p.key = seed.perm_key
on conflict do nothing;
