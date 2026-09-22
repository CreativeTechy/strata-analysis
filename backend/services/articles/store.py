"""The SAVER stage: direct Postgres upsert helpers for enriched articles."""

from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import logging

import config
import db
import dedup
from embeddings import cosine_similarity
from services.projects.projects_store import list_projects, set_article_projects
from psycopg.types.json import Jsonb
from timestamps import parse_published
from trusted_sources import is_trusted_domain

logger = logging.getLogger(__name__)

ARTICLE_COLUMNS = (
    "url", "source", "source_url", "title", "author", "published",
    "published_at", "published_precision", "text",
    "fetched_at", "summary", "sentiment", "relevance_score", "category",
    "article_category", "writer_tone", "article_tone", "region", "region_confidence", "gender", "age_range", "verified",
    "insight_json", "analysis_model", "analysis_prompt_version", "analyzed_at",
    "organizations", "entities", "topics", "key_points", "risks", "opportunities",
    "brands", "car_models", "embedding_json", "embedding_model", "embedding_source", "embedded_at",
    "sentiment_score", "sentiment_low_confidence", "sentiment_model",
    "category_confidence", "writer_tone_confidence", "article_tone_confidence",
    "classification_model", "extraction_model", "analysis_pipeline_version",
    "source_language", "source_language_confidence", "embedding_dimensions",
    "analysis_status", "analysis_error", "analysis_started_at", "analysis_finished_at",
    "analysis_attempt_count", "reprocess_requested_at", "content_hash",
    "pipeline_run_id", "source_run_snapshot", "source_provenance",
)

ARTICLE_MUTABLE_FIELDS = (
    "url",
    "source",
    "source_url",
    "title",
    "author",
    "published",
    "published_at",
    "published_precision",
    "text",
    "fetched_at",
    "summary",
    "sentiment",
    "relevance_score",
    "category",
    "article_category",
    "writer_tone",
    "article_tone",
    "region",
    "region_confidence",
    "gender",
    "age_range",
    "verified",
    "insight_json",
    "analysis_model",
    "analysis_prompt_version",
    "analyzed_at",
    "organizations",
    "entities",
    "topics",
    "key_points",
    "risks",
    "opportunities",
    "brands",
    "car_models",
    "embedding_json",
    "embedding_model",
    "embedding_source",
    "embedded_at",
    "sentiment_score",
    "sentiment_low_confidence",
    "sentiment_model",
    "category_confidence",
    "writer_tone_confidence",
    "article_tone_confidence",
    "classification_model",
    "extraction_model",
    "analysis_pipeline_version",
    "source_language",
    "source_language_confidence",
    "embedding_dimensions",
    "analysis_status",
    "analysis_error",
    "analysis_started_at",
    "analysis_finished_at",
    "analysis_attempt_count",
    "reprocess_requested_at",
    "content_hash",
    "pipeline_run_id",
    "source_run_snapshot",
    "source_provenance",
)
ARTICLE_JSON_FIELDS = {
    "insight_json",
    "organizations",
    "entities",
    "topics",
    "key_points",
    "risks",
    "opportunities",
    "brands",
    "car_models",
    "embedding_json",
}

# The AI-derived output columns, as opposed to the article's own identity/
# content fields (url, title, text, author, published, ...). Guarded
# separately in _upsert_article_row(): project_document_articles.py and
# competitor_document_articles.py both materialize a freshly-approved
# candidate by calling save_articles() with these fields still at
# DEFAULT_ENRICHMENT's neutral placeholders and analysis_status='pending' -
# real analysis for *that candidate* hasn't run yet. If the candidate's url
# happens to already belong to a successfully-analyzed article (the same
# export re-imported, or a real-world URL approved into a second project),
# `on conflict (url) do update` would otherwise blank out that existing
# analysis the moment the placeholder lands - and if the analysis run queued
# right after doesn't get around to re-analyzing this particular article
# (e.g. it was materialized after that run's own work was already selected),
# the neutral placeholder is what a viewer sees, indefinitely, in place of
# analysis that used to be there. A genuine reanalysis result is never
# written with analysis_status='pending' (see reanalyze.py), so gating on
# that incoming value only ever protects against the placeholder case.
ENRICHMENT_FIELDS = frozenset({
    "sentiment",
    "sentiment_score",
    "sentiment_low_confidence",
    "sentiment_model",
    "relevance_score",
    "category",
    "category_confidence",
    "article_category",
    "writer_tone",
    "writer_tone_confidence",
    "article_tone",
    "article_tone_confidence",
    "region",
    "region_confidence",
    "gender",
    "age_range",
    "verified",
    "insight_json",
    "analysis_model",
    "analysis_prompt_version",
    "analyzed_at",
    "organizations",
    "entities",
    "topics",
    "key_points",
    "risks",
    "opportunities",
    "brands",
    "car_models",
    "embedding_json",
    "embedding_model",
    "embedding_source",
    "embedded_at",
    "embedding_dimensions",
    "classification_model",
    "extraction_model",
    "analysis_pipeline_version",
    "source_language",
    "source_language_confidence",
})


def _row(article):
    row = {k: article.get(k) for k in ARTICLE_COLUMNS}
    # Single chokepoint for the parsed publish timestamp, so every save path
    # (pipeline, re-enrich, backfill) gets it without its own date handling.
    # `published` stays as the raw provenance string.
    if row.get("published_at") is None and not row.get("published_precision"):
        parsed, precision = parse_published(row.get("published"))
        row["published_at"] = parsed
        row["published_precision"] = precision
    return row


def _log_db_error(prefix, error):
    logger.error("%s: %s", prefix, error)


def _jsonb_param(value):
    if value is None:
        value = []
    return Jsonb(value)


def _jsonb_object_param(value):
    """Like _jsonb_param, but for an object-shaped column (source_run_snapshot)
    rather than the list-shaped ones ARTICLE_JSON_FIELDS covers - a missing
    value has to stay SQL NULL here, not fall back to `[]`."""
    return Jsonb(value) if isinstance(value, dict) else None


def _null_if_blank(value):
    text = str(value).strip() if value is not None else ""
    return text or None


def _content_hash(text):
    """Fingerprint of an article body, used to tell a re-scrape that changed
    something from one that returned the same page again.

    Whitespace is collapsed first so that markup reflowed between crawls - a
    different line-wrap, an extra blank line - is not reported as the
    competitor having done something.
    """
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _article_params(article):
    row = _row(article)
    return (
        row["url"],
        row["source"],
        row["source_url"],
        row["title"],
        row["author"],
        row["published"],
        row["text"],
        row["fetched_at"],
        row["summary"],
        row["sentiment"],
        row["relevance_score"],
        row["category"],
        row["article_category"],
        _jsonb_param(row["insight_json"]),
        row["analysis_model"],
        row["analysis_prompt_version"],
        row["analyzed_at"],
        _jsonb_param(row["organizations"]),
        _jsonb_param(row["entities"]),
        _jsonb_param(row["topics"]),
        _jsonb_param(row["key_points"]),
        _jsonb_param(row["risks"]),
        _jsonb_param(row["opportunities"]),
        _jsonb_param(row["brands"]),
        _jsonb_param(row["car_models"]),
        _jsonb_param(row["embedding_json"]),
        row["embedding_model"],
        row["embedding_source"],
        _null_if_blank(row["embedded_at"]),
    )


@lru_cache(maxsize=1)
def _article_table_columns():
    if not config.DATABASE_URL:
        return set()

    try:
        rows = db.fetch_all(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'articles'
            """
        )
    except Exception:
        return set()

    columns = set()
    for row in rows or []:
        column_name = str((row or {}).get("column_name") or "").strip()
        if column_name:
            columns.add(column_name)
    return columns


def _article_columns():
    columns = _article_table_columns()
    if columns:
        return columns
    return set(ARTICLE_MUTABLE_FIELDS)


def _article_write_fields():
    columns = _article_columns()
    return [field for field in ARTICLE_MUTABLE_FIELDS if field in columns]


def stored_article_fields():
    """The exact column list `save_articles()` writes on this database.

    Read paths that need to round-trip through the upsert (the JSONL export,
    which is re-importable) select these: the upsert sets every one of them
    from `excluded`, so anything it writes but the export omits would come
    back as NULL on re-import."""
    return list(_article_write_fields())


def _article_returning_sql():
    columns = _article_columns()
    returning = ["id", "source_url"]
    if "embedding_json" in columns:
        returning.append("embedding_json")
    if "story_id" in columns:
        returning.append("story_id")
    return ", ".join(returning)


_ARTICLE_TIMESTAMP_FIELDS = {
    "fetched_at", "analyzed_at", "embedded_at",
    "analysis_started_at", "analysis_finished_at", "reprocess_requested_at",
}


def _assign_story_group(article, saved_row):
    """Group a freshly saved article with any near-identical story already stored.

    Syndication grouping is global (project_id null) rather than per project: a
    wire story is the same story whoever is watching it, and "independent
    stories in this project" is then `count(distinct story_id)` over the
    project's articles.

    Skipped when the row already carries a story_id, so re-scraping an article
    cannot inflate a group's member_count.
    """
    if "story_id" not in _article_columns():
        return None
    if not saved_row or saved_row.get("story_id") is not None:
        return saved_row.get("story_id") if saved_row else None

    article_id = saved_row.get("id")
    if article_id is None:
        return None

    row = _row(article)
    try:
        with db.transaction() as cur:
            story_id, _created = dedup.assign_story(
                cur,
                {
                    "id": article_id,
                    "title": row.get("title"),
                    "text": row.get("text"),
                    "published_at": row.get("published_at"),
                },
                project_id=None,
            )
            if story_id is not None:
                cur.execute(
                    "update articles set story_id = %s where id = %s",
                    (story_id, article_id),
                )
        return story_id
    except Exception as exc:
        # Grouping is an enrichment of the row, not a condition of storing it.
        _log_db_error("  story grouping skipped", exc)
        return None


def _article_row(article):
    row = _row(article)
    fields = _article_write_fields()
    params = []
    for field in fields:
        value = row[field]
        if field in ARTICLE_JSON_FIELDS:
            value = _jsonb_param(value)
        elif field in _ARTICLE_TIMESTAMP_FIELDS:
            value = _null_if_blank(value)
        elif field == "analysis_status":
            # not-null column - a pipeline result that never set this
            # (shouldn't happen, but this is the write path, not the pipeline)
            # must not attempt to insert NULL into it.
            value = _null_if_blank(value) or "success"
        elif field == "embedding_dimensions":
            embedding_json = row.get("embedding_json")
            value = len(embedding_json) if isinstance(embedding_json, list) else None
        elif field == "content_hash":
            value = _content_hash(row.get("text"))
        elif field == "verified":
            # Computed from the article's own resolved publisher URL, not
            # trusted from the caller - so a stale/absent "verified" key on
            # `article` (e.g. a cached enrichment written before this field
            # existed) can never silently mark something verified.
            value = is_trusted_domain(row.get("source_url") or row.get("url"))
        elif field in ("source_run_snapshot", "source_provenance"):
            value = _jsonb_object_param(row.get(field))
        params.append(value)
    return fields, tuple(params)


def _upsert_article_row(article):
    fields, params = _article_row(article)
    if not fields:
        return None
    columns_sql = ", ".join(fields)
    values_sql = ", ".join(["%s"] * len(fields))
    returning_sql = _article_returning_sql()

    updates = [
        f"{field} = excluded.{field}"
        for field in fields
        if field not in (
            "url", "source", "source_url", "pipeline_run_id", "source_run_snapshot", "source_provenance",
        )
        and field not in ENRICHMENT_FIELDS
    ]
    if "analysis_status" in fields:
        # When content_hash is available, only preserve when the body is
        # actually the same one the analysis was derived from - otherwise a
        # materialize call whose url matches an existing article but whose
        # text differs (a re-scrape, a different tool's export of the same
        # URL) would keep sentiment/topics/embeddings computed from the OLD
        # body while text/summary below still take the new one, pairing
        # analysis with content it was never run on. Without content_hash
        # (a pre-migration database) there is nothing to compare, so this
        # falls back to guarding on analysis_status alone - the same
        # conservative behavior this guard shipped with.
        content_unchanged = (
            " and articles.content_hash is not distinct from excluded.content_hash" if "content_hash" in fields else ""
        )
        for field in fields:
            if field in ENRICHMENT_FIELDS:
                # See ENRICHMENT_FIELDS' docstring: a materialize-as-pending
                # write must not blank out analysis that already succeeded.
                updates.append(
                    f"{field} = case when excluded.analysis_status = 'pending' "
                    f"and articles.analysis_status = 'success'"
                    f"{content_unchanged} "
                    f"then articles.{field} else excluded.{field} end"
                )
    else:
        # analysis_status itself isn't in this write (a caller that never
        # touches it), so there is no 'pending' placeholder to guard against -
        # fall back to the plain overwrite for every enrichment field present.
        updates.extend(f"{field} = excluded.{field}" for field in fields if field in ENRICHMENT_FIELDS)
    if "source_url" in fields:
        # An approved uploaded-document record may carry a real per-article URL,
        # so a later import or reanalysis can collide on `url`. Keep the document
        # provenance used by the Articles document filter and Evidence snapshot.
        updates.append(
            "source_url = case when starts_with(articles.source_url, 'document://project-document/') "
            "then articles.source_url else excluded.source_url end"
        )
    if "source" in fields:
        updates.append(
            "source = case when starts_with(articles.source_url, 'document://project-document/') "
            "then articles.source else excluded.source end"
        )
    if "pipeline_run_id" in fields:
        # pipeline_run_id records which run *first* saved this article, not
        # whichever run touched it most recently - every run re-crawls all of
        # a project's sources, so a later run routinely re-upserts URLs an
        # earlier run already saved (an RSS feed re-listing the same recent
        # items, GDELT re-surfacing the same story, etc). Keeping the
        # existing value here is what makes "articles per run" mean anything;
        # the incoming value only fills in when there was none yet (a brand
        # new article, or a legacy pre-tracking row).
        updates.append("pipeline_run_id = coalesce(articles.pipeline_run_id, excluded.pipeline_run_id)")
    if "source_run_snapshot" in fields:
        # Set once, at candidate-approval time (project_document_articles.py),
        # from provenance a scraper-app export carried in. A later save of the
        # same article - a reanalyze pass, a re-approval - has no snapshot of
        # its own to offer, and must not blank out the one already recorded.
        updates.append(
            "source_run_snapshot = coalesce(articles.source_run_snapshot, excluded.source_run_snapshot)"
        )
    if "source_provenance" in fields:
        updates.append(
            "source_provenance = coalesce(articles.source_provenance, excluded.source_provenance)"
        )
    # Advanced only when the body actually differs, which is what makes
    # "this page changed" distinguishable from "we crawled this page again".
    # Every SET expression is evaluated against the pre-update row, so
    # `articles.content_hash` here is the previously stored fingerprint even
    # though the same statement is also overwriting it. New rows get their
    # value from the column default (migration 0017), not from this clause.
    if "content_hash" in fields and "content_changed_at" in _article_columns():
        updates.append(
            "content_changed_at = case"
            " when articles.content_hash is distinct from excluded.content_hash then now()"
            " else articles.content_changed_at end"
        )

    return db.fetch_one(
        """
        insert into articles ({columns})
        values ({values})
        on conflict (url) do update set
            {updates}
        returning {returning}
        """.format(
            columns=columns_sql,
            values=values_sql,
            updates=", ".join(updates),
            returning=returning_sql,
        ),
        params,
    )


@lru_cache(maxsize=16)
def _table_exists(table_name):
    """Whether a given public table exists yet - lets the normalized child
    tables (article_feedback_items, idea_clusters, ...) be written to
    opportunistically without breaking the core article upsert on a
    database that hasn't had schema.sql re-run yet."""
    if not config.DATABASE_URL:
        return False
    try:
        row = db.fetch_one(
            """
            select exists (
                select 1 from information_schema.tables
                where table_schema = 'public' and table_name = %s
            ) as exists
            """,
            (table_name,),
        )
        return bool((row or {}).get("exists"))
    except Exception:
        return False


@lru_cache(maxsize=32)
def _table_columns(table_name):
    """The columns a given public table actually has, on this database.

    Mirrors _article_columns()'s reasoning for the `articles` table, extended
    to the child tables: a migration can land after the code that depends on
    it (a deploy where MIGRATE_ON_STARTUP=false, or a rolling restart while
    several replicas share one database), and a table existing is not the
    same as a specific column existing on it. Callers use this to drop a
    column from a write rather than let the whole write fail and, worse,
    leave a preceding delete-in-the-same-function uncommitted-by-nothing
    (each db.execute() commits on its own - see _replace_article_children)."""
    if not config.DATABASE_URL:
        return set()
    try:
        rows = db.fetch_all(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'public' and table_name = %s
            """,
            (table_name,),
        )
    except Exception:
        return set()
    return {str((row or {}).get("column_name") or "").strip() for row in rows or []} - {""}


def _bulk_insert(table, columns, rows):
    """INSERT many rows in one round trip. `table`/`columns` are always
    internal constants (never user input), so building the identifier list
    with an f-string here is safe - only the row values are parameterized."""
    if not rows:
        return
    columns_sql = ", ".join(columns)
    placeholder_row = "(" + ", ".join(["%s"] * len(columns)) + ")"
    values_sql = ", ".join([placeholder_row] * len(rows))
    params = tuple(value for row in rows for value in row)
    db.execute(f"insert into {table} ({columns_sql}) values {values_sql}", params)


FEEDBACK_ITEM_TYPES = (
    "positive_feedback", "negative_feedback", "nice_to_have_features", "complaints",
    "great_features", "comfort_issues", "performance_feedback", "price_value_feedback",
    "maintenance_reliability_feedback", "technology_feedback", "safety_feedback",
    "key_points", "risks", "opportunities",
)


def _replace_article_children(article_id, article):
    """Fully replace the normalized per-article rows (feedback items, people
    opinions, tags) for one article. Delete-then-insert so reprocessing an
    article never leaves stale rows from its previous analysis behind.

    These tables are additive/new - on a database that hasn't had schema.sql
    re-run yet they simply don't exist, so this silently no-ops rather than
    breaking the article upsert itself."""
    from services.articles.idea_clustering import _resolve_segment_label

    if not _table_exists("article_feedback_items"):
        return
    try:
        db.execute("delete from article_feedback_items where article_id = %s", (article_id,))
        db.execute("delete from article_people_opinions where article_id = %s", (article_id,))
        db.execute("delete from article_tags where article_id = %s", (article_id,))

        feedback_rows = []
        for feedback_type in FEEDBACK_ITEM_TYPES:
            for text in article.get(feedback_type) or []:
                text = str(text).strip()
                if text:
                    feedback_rows.append((article_id, feedback_type, text))
        _bulk_insert("article_feedback_items", ("article_id", "feedback_type", "text"), feedback_rows)

        # gender_evidence/age_evidence are newer columns (migrations 0019 and
        # 0021) - a database that hasn't had one applied yet (MIGRATE_ON_STARTUP=
        # false, or a replica mid-rollout) still has article_people_opinions
        # itself, so the table-existence check above passes but this insert
        # would otherwise name a column that doesn't exist and fail the whole
        # child write, including article_tags below (the deletes above have
        # already committed by then - see _table_exists's docstring on
        # db.execute).
        existing_columns = _table_columns("article_people_opinions")
        has_gender_evidence = "gender_evidence" in existing_columns
        has_age_evidence = "age_evidence" in existing_columns
        if not has_gender_evidence or not has_age_evidence:
            # _table_columns is memoized for the life of the process, which is
            # right for the steady state but wrong for a "not there yet"
            # answer: a column is only ever added, never dropped, so a cached
            # miss would keep this process writing no evidence even after the
            # migration lands - until someone restarts it. Drop the memo so
            # the next article re-checks. Safe to clear wholesale: this is
            # the only caller.
            _table_columns.cache_clear()
        opinion_columns = (
            "article_id", "opinion", "sentiment", "category", "gender",
        ) + (("gender_evidence",) if has_gender_evidence else ()) + (
            "age_range",
        ) + (("age_evidence",) if has_age_evidence else ()) + (
            "region", "segment_raw", "segment",
        )

        opinion_rows = []
        segment_votes = Counter()
        for item in article.get("people_opinions") or []:
            if not isinstance(item, dict):
                continue
            opinion = str(item.get("opinion") or "").strip()
            if not opinion:
                continue
            sentiment = str(item.get("sentiment") or "neutral").strip().lower() or "neutral"
            category = str(item.get("category") or "").strip()
            gender = str(item.get("gender") or "unknown").strip().lower() or "unknown"
            # Only meaningful (and only ever set upstream) alongside a resolved
            # gender/age_range - see normalize.normalize_gender_evidence's and
            # normalize_age_evidence's docstrings.
            gender_evidence = str(item.get("gender_evidence") or "").strip() if gender != "unknown" else ""
            age_range = str(item.get("age_range") or "unknown").strip().lower() or "unknown"
            age_evidence = str(item.get("age_evidence") or "").strip() if age_range != "unknown" else ""
            region = str(item.get("region") or "unknown").strip() or "unknown"
            segment_raw = str(item.get("segment") or "unknown").strip() or "unknown"
            segment = _resolve_segment_label(segment_raw)
            if segment != "unknown":
                segment_votes[segment] += 1
            row = (article_id, opinion, sentiment, category, gender)
            if has_gender_evidence:
                row += (gender_evidence,)
            row += (age_range,)
            if has_age_evidence:
                row += (age_evidence,)
            row += (region, segment_raw, segment)
            opinion_rows.append(row)
        _bulk_insert("article_people_opinions", opinion_columns, opinion_rows)
        if segment_votes:
            db.execute(
                "update articles set segment = %s where id = %s",
                (segment_votes.most_common(1)[0][0], article_id),
            )

        tag_rows = []
        for tag_type, field in (("organization", "organizations"), ("entity", "entities"), ("topic", "topics")):
            for value in article.get(field) or []:
                value = str(value).strip()
                if value:
                    tag_rows.append((article_id, tag_type, value))
        _bulk_insert("article_tags", ("article_id", "tag_type", "value"), tag_rows)
    except Exception as e:
        _log_db_error(f"  article child-table write error for article {article_id}", e)


def _source_key(article):
    return (article.get("source_name") or article.get("source") or "unknown").strip() or "unknown"


def save_articles(articles, batch_size=50, project_id=None, run_id=None):
    """Upserts articles and returns (total_saved, saved_count_by_source).

    `project_id` links every saved article to that project and scopes their
    idea-cluster attribution to it. Every caller runs in-process and knows
    which project it is acting for, so it is always passed explicitly.

    `run_id` tags every saved article with the analysis run that produced it,
    so dashboard/reports stats can be scoped to one run. Left None (an upload
    or import, which is not a run), `_upsert_article_row` treats it as "don't
    touch the existing value".
    """
    from services.articles.idea_clustering import _replace_idea_clusters_for_article

    if not config.DATABASE_URL:
        logger.warning("Database credentials not set, skipping upload.")
        return 0, {}

    sent = 0
    saved_by_source = defaultdict(int)

    linked_articles = defaultdict(set)
    linked_scores = defaultdict(dict)
    project_embedding_cache = None
    project_embedding_map = {}

    def _load_project_embedding_map():
        nonlocal project_embedding_cache, project_embedding_map
        if project_embedding_cache is not None:
            return project_embedding_map

        project_embedding_cache = list_projects()
        project_embedding_map = {}
        for project in project_embedding_cache or []:
            try:
                project_id_value = int(project.get("id"))
            except Exception:
                continue
            embedding = project.get("embedding_json") or []
            if isinstance(embedding, list) and embedding:
                project_embedding_map[project_id_value] = embedding
        return project_embedding_map

    for i in range(0, len(articles), batch_size):
        source_batch = articles[i:i + batch_size]
        try:
            persisted = []
            for article in source_batch:
                if run_id:
                    article["pipeline_run_id"] = run_id
                row = _upsert_article_row(article)
                if row:
                    _assign_story_group(article, row)
                    persisted.append((article, row))
                    sent += 1
                    saved_by_source[_source_key(article)] += 1

            for article, row in persisted:
                if not isinstance(row, dict):
                    continue
                try:
                    article_id = int(row.get("id"))
                except Exception:
                    continue

                _replace_article_children(article_id, article)
                _replace_idea_clusters_for_article(article_id, project_id, article.get("frequent_ideas"))

                # An article belongs to the project the caller named - the
                # document it was split out of, or the import that brought it
                # in. (The crawler this was forked from also inferred linkage
                # from which configured source fetched the URL; there are no
                # sources here, so the explicit link is the only one.)
                if project_id is not None:
                    linked_articles[project_id].add(article_id)

                article_embedding = article.get("embedding_json") or row.get("embedding_json") or []
                if isinstance(article_embedding, list) and article_embedding:
                    project_embeddings = _load_project_embedding_map()
                    best_project_id = None
                    best_score = 0.0
                    for candidate_project_id, candidate_embedding in project_embeddings.items():
                        score = cosine_similarity(article_embedding, candidate_embedding)
                        if score > best_score:
                            best_score = score
                            best_project_id = candidate_project_id
                    if best_project_id is not None and best_score >= config.PROJECT_ATTRIBUTION_SIMILARITY_THRESHOLD:
                        linked_articles[best_project_id].add(article_id)
                        linked_scores[best_project_id][article_id] = best_score
            logger.info("Uploaded batch %s (%s articles)", i // batch_size + 1, len(source_batch))
        except Exception as e:
            _log_db_error(f"  Database upload error for batch {i // batch_size + 1}", e)

    if linked_articles:
        for linked_project_id, article_ids in linked_articles.items():
            set_article_projects(sorted(article_ids), linked_project_id, similarity_scores=linked_scores.get(linked_project_id, {}))

    return sent, dict(saved_by_source)


def delete_all_articles():
    if not config.DATABASE_URL:
        logger.warning("Database credentials not set, skipping article delete.")
        return 0

    try:
        db.execute("delete from articles")
        return 1
    except Exception as e:
        _log_db_error("  article delete error", e)
        return 0


def delete_article(article_id):
    if not config.DATABASE_URL:
        logger.warning("Database credentials not set, skipping article delete.")
        return False

    try:
        row = db.execute("delete from articles where id = %s returning id", (article_id,))
        return row is not None
    except Exception as e:
        _log_db_error("  article delete error", e)
        return False
