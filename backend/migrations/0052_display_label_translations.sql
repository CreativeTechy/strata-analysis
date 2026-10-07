-- Locale-rendered display labels for open-ended analysis values the
-- dashboard shows as-is: free-text demographic buckets (segments, regions
-- that aren't a canonical country) and survey metadata (question,
-- population, cohort, answer). See services/i18n/label_translation.py.
--
-- Keyed on the source text alone (per locale), not per project: like
-- project_frequent_idea_translations, a label's translation doesn't depend
-- on where it was counted, and these are short labels rather than document
-- content, so one cache serves every project and every view.
create table if not exists public.display_label_translations (
    id               bigint generated always as identity primary key,
    locale           text not null,
    source_text      text not null,
    translated_text  text not null,
    model            text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    constraint display_label_translations_key unique (locale, source_text)
);

drop trigger if exists set_display_label_translations_updated_at on public.display_label_translations;
create trigger set_display_label_translations_updated_at
before update on public.display_label_translations
for each row
execute function public.set_updated_at();
