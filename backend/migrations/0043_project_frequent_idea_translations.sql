-- Locale-rendered strings for the dashboard's "Top Ideas" widget
-- (services/intelligence/idea_translation.py), which reads
-- insights.frequent_ideas - a Counter-based rollup computed fresh on every
-- /api/projects/{id}/intelligence request from articles.insight_json, not a
-- persisted row. There is no canonical row/updated_at to key a cache on the
-- way article_translations or project_trend_summaries_localized do; instead
-- this is keyed directly on the idea's own text, since a given idea string's
-- translation does not depend on which period/run it was counted in.
create table if not exists public.project_frequent_idea_translations (
    id               bigint generated always as identity primary key,
    project_id       bigint not null references public.projects(id) on delete cascade,
    locale           text not null,
    source_idea      text not null,
    translated_idea  text not null,
    model            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    constraint project_frequent_idea_translations_key unique (project_id, locale, source_idea)
);

create index if not exists project_frequent_idea_translations_project_idx
    on public.project_frequent_idea_translations (project_id, locale);

drop trigger if exists set_project_frequent_idea_translations_updated_at on public.project_frequent_idea_translations;
create trigger set_project_frequent_idea_translations_updated_at
before update on public.project_frequent_idea_translations
for each row
execute function public.set_updated_at();
