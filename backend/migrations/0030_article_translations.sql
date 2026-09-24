-- Locale-rendered view of one article's structured-extraction output fields
-- (services/articles/translation.py). The articles table itself stays in
-- whatever language the extraction stage produced (see
-- analysis/structured_extraction.py) - that is the canonical version search,
-- export, and cross-article comparison keep reading. A viewer requesting a
-- non-default locale gets that same content rendered into their locale,
-- generated once and cached here rather than re-translated on every request.
--
-- Invalidated by the article's own `analyzed_at` changing (a reanalysis that
-- replaced the extraction this was rendered from), not by time - see
-- translation.py's `source_analyzed_at` comparison.
create table if not exists public.article_translations (
    id                  bigint generated always as identity primary key,
    article_id          bigint not null references public.articles(id) on delete cascade,
    locale              text not null,
    translated          jsonb not null,
    source_analyzed_at  timestamptz,
    model               text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint article_translations_article_locale_key unique (article_id, locale)
);

create index if not exists article_translations_article_idx
    on public.article_translations (article_id, locale);

drop trigger if exists set_article_translations_updated_at on public.article_translations;
create trigger set_article_translations_updated_at
before update on public.article_translations
for each row
execute function public.set_updated_at();
