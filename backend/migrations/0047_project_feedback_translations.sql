-- Locale-rendered strings for the Reports page's "Categorized feedback"
-- section (services/intelligence/feedback_translation.py), which reads
-- insights.positive_feedback/negative_feedback - a rollup computed fresh on
-- every /api/projects/{id}/intelligence request from articles.insight_json,
-- not a persisted row. Same reasoning as
-- project_frequent_idea_translations: keyed on the feedback item's own text
-- rather than on request scope, since a given phrase translates the same way
-- regardless of which period/run it was counted in.
create table if not exists public.project_feedback_translations (
    id               bigint generated always as identity primary key,
    project_id       bigint not null references public.projects(id) on delete cascade,
    locale           text not null,
    source_text      text not null,
    translated_text  text not null,
    model            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    constraint project_feedback_translations_key unique (project_id, locale, source_text)
);

create index if not exists project_feedback_translations_project_idx
    on public.project_feedback_translations (project_id, locale);

drop trigger if exists set_project_feedback_translations_updated_at on public.project_feedback_translations;
create trigger set_project_feedback_translations_updated_at
before update on public.project_feedback_translations
for each row
execute function public.set_updated_at();
