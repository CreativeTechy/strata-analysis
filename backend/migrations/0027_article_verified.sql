-- Marks an article as coming from a well-known, editorially-reputable
-- publisher domain (see backend/trusted_sources.py's TRUSTED_DOMAINS),
-- computed from the article's own resolved URL at save time (see
-- services/articles/store.py's _article_row) rather than inherited from its
-- configured `sources` row - a keyword/hashtag source can resolve to a
-- different publisher per article, so trust has to be judged per-article.
alter table public.articles
    add column if not exists verified boolean not null default false;

create index if not exists articles_verified_idx on public.articles (verified);
