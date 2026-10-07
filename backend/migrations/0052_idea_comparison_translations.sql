-- Locale-rendered strings for the dashboard's "Idea comparisons across
-- sources" card (services/articles/idea_comparison_translation.py): the idea
-- title, the divergence summary and each source's stated value. Like
-- project_frequent_idea_translations this is keyed on the source text itself
-- (by hash, since summaries can be long) rather than on a comparison row,
-- because comparisons are rewritten on every regenerate - an unchanged string
-- keeps its cached translation, a changed one simply misses and is retranslated.
create table if not exists public.idea_comparison_text_translations (
    id               bigint generated always as identity primary key,
    project_id       bigint not null references public.projects(id) on delete cascade,
    locale           text not null,
    source_hash      text not null,
    translated_text  text not null,
    model            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    constraint idea_comparison_text_translations_key unique (project_id, locale, source_hash)
);

drop trigger if exists set_idea_comparison_text_translations_updated_at on public.idea_comparison_text_translations;
create trigger set_idea_comparison_text_translations_updated_at
before update on public.idea_comparison_text_translations
for each row
execute function public.set_updated_at();
