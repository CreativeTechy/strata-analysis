"""Cross-article idea/segment clustering: the embedding-based attach-or-create
pattern that groups a freshly analyzed article's frequent_ideas and
people_opinions.segment values onto a shared, growing vocabulary instead of
each phrasing spawning its own one-off bucket.

Two independent taxonomies share the same pattern (exact-match first, cosine
similarity against existing labels as a fallback, insert a new one on a
miss) but are otherwise unrelated: idea_clusters is project-scoped (an idea
is specific to one project's competitive space); segment_taxonomy is global
(a life-situation label like "laid off" means the same thing everywhere).

Depends on services.articles.store only for _table_exists (every table here
is additive/new, so a database that hasn't had schema.sql re-run yet must
silently no-op rather than break the article upsert this feeds into) -
store.py imports back from here lazily (inside save_articles()/
_replace_article_children()) to avoid a top-level import cycle.
"""

from __future__ import annotations

import db
from embeddings import cosine_similarity, get_embedding
from psycopg.types.json import Jsonb
from services.articles.store import _table_exists


def _jsonb_param(value):
    if value is None:
        value = []
    return Jsonb(value)


def _log_db_error(prefix, error):
    print(f"{prefix}: {error}")


# A new idea that doesn't exact-match an existing cluster still attaches to it
# if their embeddings score at or above this - a conservative starting point
# favoring precision (avoid wrongly merging distinct ideas) over recall, in
# the same spirit as this codebase's other hardcoded similarity thresholds
# (project attribution 0.78 in store.py, competitor matching 0.62, search 0.28).
# Tune by editing this constant; not empirically validated yet.
IDEA_SIMILARITY_THRESHOLD = 0.86

# Same idea, applied to segment_taxonomy (see _resolve_segment_label): a new
# raw segment phrase attaches to an existing canonical label at or above this
# score. Segment phrases are short (2-4 words) so a slightly lower bar than
# IDEA_SIMILARITY_THRESHOLD is used - short phrases tend to score lower on
# cosine similarity than full sentences even when they mean the same thing.
# Conservative starting point, not empirically validated yet.
SEGMENT_SIMILARITY_THRESHOLD = 0.80


def _resolve_segment_label(raw_text):
    """Maps a freeform per-person life-situation/occupation phrase (see
    structured_extraction.py's people_opinions.segment) onto a shared
    vocabulary so "jobless"/"laid off"/"unemployed" land in the same
    dashboard bucket instead of each spawning its own tiny slice.

    Exact normalized-text match against segment_taxonomy first; cosine
    similarity against every other canonical label as a fallback - the same
    embedding-based attach-or-create pattern as _resolve_idea_cluster_id, but
    global instead of project-scoped, since a life-situation label isn't
    specific to one project's competitive space the way an idea is."""
    text = (raw_text or "").strip()
    if not text or text.lower() == "unknown":
        return "unknown"
    if not _table_exists("segment_taxonomy"):
        return text

    existing = db.fetch_one(
        "select canonical_label from segment_taxonomy where lower(canonical_label) = lower(%s)",
        (text,),
    )
    if existing:
        db.execute(
            "update segment_taxonomy set last_seen_at = now() where canonical_label = %s",
            (existing["canonical_label"],),
        )
        return existing["canonical_label"]

    embedding = get_embedding(text)
    if embedding.get("embedding_json"):
        candidates = db.fetch_all("select canonical_label, embedding_json from segment_taxonomy")
        best_label, best_score = None, 0.0
        for candidate in candidates or []:
            candidate_embedding = candidate.get("embedding_json") or []
            if not candidate_embedding:
                continue
            score = cosine_similarity(embedding["embedding_json"], candidate_embedding)
            if score > best_score:
                best_score, best_label = score, candidate["canonical_label"]

        if best_label is not None and best_score >= SEGMENT_SIMILARITY_THRESHOLD:
            db.execute(
                "update segment_taxonomy set last_seen_at = now() where canonical_label = %s",
                (best_label,),
            )
            return best_label

        db.execute(
            """
            insert into segment_taxonomy (
                canonical_label, embedding_json, embedding_model, embedding_source, embedded_at
            )
            values (%s, %s, %s, %s, %s)
            on conflict (canonical_label) do update set last_seen_at = now()
            """,
            (
                text,
                _jsonb_param(embedding["embedding_json"]),
                embedding["embedding_model"],
                embedding["embedding_source"],
                embedding["embedded_at"],
            ),
        )
        return text

    # Embeddings unavailable (model not installed/failed to load) - fall back
    # to an exact-match-only insert, identical to pre-embedding behavior.
    db.execute(
        """
        insert into segment_taxonomy (canonical_label)
        values (%s)
        on conflict (canonical_label) do update set last_seen_at = now()
        """,
        (text,),
    )
    return text


def _touch_idea_cluster(cluster_id):
    db.execute(
        "update idea_clusters set last_seen_at = now(), updated_at = now() where id = %s",
        (cluster_id,),
    )


def _resolve_idea_cluster_id(project_id, idea, idea_type, category):
    """Find or create the idea_clusters row this (idea, type, category) belongs
    to. Exact normalized-text match is tried first (free, and the common case
    for literal repeats); if that misses, falls back to cosine similarity
    against the project's other clusters of the same type - not category,
    since category wording can vary across articles for the same underlying
    idea - so a differently-worded restatement of the same point attaches to
    the existing cluster instead of spawning a near-duplicate. Clusters
    missing an embedding (pre-dating this feature, or created when embedding
    generation failed) are backfilled lazily here rather than via a one-off
    migration."""
    existing = db.fetch_one(
        """
        select id from idea_clusters
        where project_id = %s and normalized_idea = lower(trim(%s)) and type = %s and category = %s
        """,
        (project_id, idea, idea_type, category),
    )
    if existing:
        _touch_idea_cluster(existing["id"])
        return existing["id"]

    embedding = get_embedding(idea)
    if embedding.get("embedding_json"):
        candidates = db.fetch_all(
            "select id, idea, embedding_json from idea_clusters where project_id = %s and type = %s",
            (project_id, idea_type),
        )
        best_id, best_score = None, 0.0
        for candidate in candidates or []:
            candidate_embedding = candidate.get("embedding_json") or []
            if not candidate_embedding:
                backfilled = get_embedding(candidate.get("idea") or "")
                if backfilled.get("embedding_json"):
                    candidate_embedding = backfilled["embedding_json"]
                    db.execute(
                        """
                        update idea_clusters set
                            embedding_json = %s, embedding_model = %s,
                            embedding_source = %s, embedded_at = %s
                        where id = %s
                        """,
                        (
                            _jsonb_param(backfilled["embedding_json"]),
                            backfilled["embedding_model"],
                            backfilled["embedding_source"],
                            backfilled["embedded_at"],
                            candidate["id"],
                        ),
                    )
            score = cosine_similarity(embedding["embedding_json"], candidate_embedding)
            if score > best_score:
                best_score, best_id = score, candidate["id"]

        if best_id is not None and best_score >= IDEA_SIMILARITY_THRESHOLD:
            _touch_idea_cluster(best_id)
            return best_id

        row = db.fetch_one(
            """
            insert into idea_clusters (
                project_id, idea, type, category,
                embedding_json, embedding_model, embedding_source, embedded_at
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (project_id, normalized_idea, type, category) do update set
                last_seen_at = now(), updated_at = now()
            returning id
            """,
            (
                project_id, idea, idea_type, category,
                _jsonb_param(embedding["embedding_json"]),
                embedding["embedding_model"],
                embedding["embedding_source"],
                embedding["embedded_at"],
            ),
        )
        return row["id"] if row else None

    # Embeddings unavailable (model not installed/failed to load) - fall back
    # to the original exact-match-only insert, identical to pre-embedding
    # behavior.
    row = db.fetch_one(
        """
        insert into idea_clusters (project_id, idea, type, category)
        values (%s, %s, %s, %s)
        on conflict (project_id, normalized_idea, type, category) do update set
            last_seen_at = now(), updated_at = now()
        returning id
        """,
        (project_id, idea, idea_type, category),
    )
    return row["id"] if row else None


def _replace_idea_clusters_for_article(article_id, project_id, frequent_ideas):
    """Link/unlink this article from its project's idea_clusters and
    recompute frequency_estimate for every affected cluster. Idea clusters
    are project-scoped (there is no meaningful global cluster), so this is a
    no-op without a project_id, and a no-op if idea_clusters hasn't been
    created yet (pre-migration database)."""
    if project_id is None or not _table_exists("idea_clusters"):
        return
    try:
        previous = db.fetch_all(
            "select idea_cluster_id from idea_cluster_articles where article_id = %s",
            (article_id,),
        )
        previous_ids = {row["idea_cluster_id"] for row in previous or []}

        db.execute("delete from idea_cluster_articles where article_id = %s", (article_id,))

        new_cluster_ids = set()
        for item in frequent_ideas or []:
            if not isinstance(item, dict):
                continue
            idea = str(item.get("idea") or "").strip()
            if not idea:
                continue
            idea_type = str(item.get("type") or "issue").strip().lower() or "issue"
            if idea_type not in {"complaint", "praise", "suggestion", "issue"}:
                idea_type = "issue"
            category = str(item.get("category") or "").strip()

            cluster_id = _resolve_idea_cluster_id(project_id, idea, idea_type, category)
            if cluster_id is None:
                continue
            new_cluster_ids.add(cluster_id)
            db.execute(
                "insert into idea_cluster_articles (idea_cluster_id, article_id) values (%s, %s) "
                "on conflict do nothing",
                (cluster_id, article_id),
            )

        for cluster_id in previous_ids | new_cluster_ids:
            db.execute(
                """
                update idea_clusters set frequency_estimate = (
                    select count(*) from idea_cluster_articles where idea_cluster_id = %s
                )
                where id = %s
                """,
                (cluster_id, cluster_id),
            )
    except Exception as e:
        _log_db_error(f"  idea cluster write error for article {article_id}", e)
