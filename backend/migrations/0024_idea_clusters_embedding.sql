-- Embedding of an idea_clusters row's own idea text, so a new frequent_idea
-- that doesn't exact-match an existing cluster (project, normalized idea,
-- type, category) can still be attached to it via cosine similarity instead
-- of spawning a near-duplicate cluster. Mirrors the same
-- embedding_json/embedding_model/embedding_source/embedded_at columns already
-- used on `articles`/`projects`/`competitors`, so `embeddings.cosine_similarity`
-- and the existing in-Python comparison pattern (see store.py's project-
-- attribution matching) work unchanged against this column too.
alter table public.idea_clusters
    add column if not exists embedding_json jsonb default '[]'::jsonb,
    add column if not exists embedding_model text,
    add column if not exists embedding_source text,
    add column if not exists embedded_at timestamptz;
