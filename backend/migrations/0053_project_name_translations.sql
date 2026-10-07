-- Locale-rendered project names (services/projects/project_name_translations.py).
-- Keyed on the name's own text so renaming a project naturally misses the
-- cache and re-translates, with no invalidation logic.
create table if not exists public.project_name_translations (
    id               bigint generated always as identity primary key,
    project_id       bigint not null references public.projects(id) on delete cascade,
    locale           text not null,
    source_name      text not null,
    translated_name  text not null,
    model            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    constraint project_name_translations_key unique (project_id, locale, source_name)
);

create index if not exists project_name_translations_project_idx
    on public.project_name_translations (project_id, locale);

drop trigger if exists set_project_name_translations_updated_at on public.project_name_translations;
create trigger set_project_name_translations_updated_at
before update on public.project_name_translations
for each row
execute function public.set_updated_at();
