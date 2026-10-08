-- Locale-rendered competitor names
-- (services/competitors/competitor_name_translations.py). Scoped to the study
-- (project) the competitor belongs to, so it goes with the study (cascade),
-- and keyed on the name's own text so renaming a competitor naturally misses
-- the cache and re-translates, with no invalidation logic - same shape as
-- project_name_translations.
create table if not exists public.competitor_name_translations (
    id               bigint generated always as identity primary key,
    project_id       bigint not null references public.projects(id) on delete cascade,
    locale           text not null,
    source_name      text not null,
    translated_name  text not null,
    model            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    constraint competitor_name_translations_key unique (project_id, locale, source_name)
);

drop trigger if exists set_competitor_name_translations_updated_at on public.competitor_name_translations;
create trigger set_competitor_name_translations_updated_at
before update on public.competitor_name_translations
for each row
execute function public.set_updated_at();
