-- Embedding of a competitor's own identity (name, aliases, description), so
-- article-attribution can fall back to semantic similarity when a competitor
-- is never named literally in the text (a rebrand, a translation, an indirect
-- reference) - the existing text-mention gate in competitor_analysis.py only
-- ever finds a competitor that appears by name. Mirrors the same
-- embedding_json/embedding_model/embedding_source/embedded_at columns already
-- used on `projects` and `articles`, so `embeddings.cosine_similarity` and the
-- existing in-Python comparison pattern (see articles_store.py / store.py's
-- project-attribution matching) work unchanged against this column too.
alter table public.competitors
    add column if not exists embedding_json jsonb default '[]'::jsonb,
    add column if not exists embedding_model text,
    add column if not exists embedding_source text,
    add column if not exists embedded_at timestamptz;
