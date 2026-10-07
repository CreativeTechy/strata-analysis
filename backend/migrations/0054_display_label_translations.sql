-- Locale-rendered display labels for open-ended analysis values the
-- dashboard shows as-is: free-text demographic buckets (segments, regions
-- that aren't a canonical country) and survey metadata (question,
-- population, cohort, answer). See services/i18n/label_translation.py.
--
-- Scoped per project like project_frequent_idea_translations: the source
-- text comes out of that project's uploaded documents, so it is removed with
-- the project (cascade) and with its other derived data when its articles are
-- removed (store.py's _PROJECT_DERIVED_TABLES), and one project's cached
-- translation is never served to another.
create table if not exists public.display_label_translations (
    id               bigint generated always as identity primary key,
    project_id       bigint not null references public.projects(id) on delete cascade,
    locale           text not null,
    source_text      text not null,
    translated_text  text not null,
    model            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    constraint display_label_translations_key unique (project_id, locale, source_text)
);

drop trigger if exists set_display_label_translations_updated_at on public.display_label_translations;
create trigger set_display_label_translations_updated_at
before update on public.display_label_translations
for each row
execute function public.set_updated_at();
