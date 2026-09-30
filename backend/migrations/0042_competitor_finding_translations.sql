-- Locale-rendered view of one competitor finding's LLM-generated output
-- fields (services/competitors/finding_translation.py). competitor_findings
-- itself stays canonical English - generate_finding() writes it once and
-- nothing after that mutates headline/whats_up/impact/confidence_reason/
-- signals/actions (only validation_status/validation_notes change via
-- set_finding_validation()), so unlike article_translations/
-- project_trend_summaries_localized there is no reanalysis/regeneration to
-- key invalidation on - a finding's own immutable `generated_at` is stored
-- alongside the cached rendering purely as a belt-and-suspenders check.
create table if not exists public.competitor_finding_translations (
    id                   bigint generated always as identity primary key,
    finding_id           bigint not null references public.competitor_findings(id) on delete cascade,
    locale               text not null,
    translated           jsonb not null,
    source_generated_at  timestamptz,
    model                text,
    created_at           timestamptz not null default now(),
    updated_at           timestamptz not null default now(),
    constraint competitor_finding_translations_finding_locale_key unique (finding_id, locale)
);

create index if not exists competitor_finding_translations_finding_idx
    on public.competitor_finding_translations (finding_id, locale);

drop trigger if exists set_competitor_finding_translations_updated_at on public.competitor_finding_translations;
create trigger set_competitor_finding_translations_updated_at
before update on public.competitor_finding_translations
for each row
execute function public.set_updated_at();
