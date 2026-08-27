"""Base read access to the articles table: filtering, paging, sorting, the
idea-cluster and per-article-analysis lookups, and the JSONL export's wider
column selection.

This is the layer articles_search.py (ranking/scoring) and
articles_analytics.py (rollups) both build on; it must not import either -
articles_store.py is what composes all three back into one browsing API.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache

import config
import db
from services.projects.projects_store import list_article_ids_for_project

ARTICLES_SELECT = (
    "id,url,source,source_url,title,author,published,text,fetched_at,summary,"
    "sentiment,relevance_score,category,article_category,writer_tone,article_tone,region,gender,age_range,segment,verified,"
    "insight_json,analysis_model,"
    "analysis_prompt_version,analyzed_at,organizations,entities,topics,key_points,"
    "risks,opportunities,brands,car_models,embedding_json,embedding_model,embedding_source,embedded_at,created_at,"
    "source_language,source_language_confidence"
)


@lru_cache(maxsize=1)
def _export_select():
    """The wider column list used by the JSONL export.

    ARTICLES_SELECT is tuned for the dashboard's article cards and omits a lot
    of what the row actually stores (sentiment_score, the per-stage confidences
    and model names, published_at/precision, analysis_status, ...). The upsert
    behind the import endpoint writes *every* mutable column from `excluded`,
    so exporting the narrow list and re-importing it would null those out.
    Selecting exactly what the upsert writes keeps export -> import lossless.

    Built from the live table rather than hardcoded so a database that hasn't
    had every migration applied yet exports the columns it does have instead of
    failing the whole query on one missing name."""
    from services.articles.store import stored_article_fields

    fields = ["id", *stored_article_fields(), "created_at"]
    seen = set()
    ordered = []
    for field in fields:
        if field not in seen:
            seen.add(field)
            ordered.append(field)
    return ",".join(ordered)


VALID_TONES = {
    "neutral",
    "positive",
    "enthusiastic",
    "optimistic",
    "critical",
    "skeptical",
    "negative",
    "concerned",
    "angry",
    "sarcastic",
    "humorous",
    "formal",
    "informal",
}

SORTABLE_COLUMNS = {
    "published",
    "relevance_score",
    "created_at",
    "title",
    "source",
    "category",
    "sentiment",
}

MAX_LIMIT = 100
# Page size for internal readers that walk the whole result set (export,
# search scan, stats). Distinct from MAX_LIMIT, which caps what one *API*
# response may return and must not silently cap a bulk read: a loop that asks
# _fetch_articles for more than its ceiling gets a short page back and reads
# that as "no more rows", stopping at MAX_LIMIT. Bulk callers therefore pass
# max_limit=BULK_PAGE_SIZE so the page they ask for is the page they get.
BULK_PAGE_SIZE = 500
DEFAULT_LIMIT = 24
DEFAULT_SORT = "published.desc"


def _normalize_text(value: str | None) -> str:
    return (value or "").strip()


def _normalize_sentiment(value: str | None) -> str:
    return _normalize_text(value).lower()


def _normalize_category(value: str | None) -> str:
    return _normalize_text(value).lower()


def _normalize_article_category(value: str | None) -> str:
    return _normalize_text(value).lower() or "general_article"


def _normalize_tone(value: str | None) -> str:
    tone = _normalize_text(value).lower()
    return tone if tone in VALID_TONES else "neutral"


def _normalize_date_bound(value: str | None) -> str:
    """Validate a date/datetime filter bound before it reaches SQL.

    An invalid value is dropped (treated as "no bound") rather than sent to
    Postgres, so a bad query param can't blow up the request or silently
    zero out a report - it just falls back to unfiltered for that bound.
    """
    text = _normalize_text(value)
    if not text:
        return ""
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return text


def _normalize_limit(value, default=DEFAULT_LIMIT, max_limit=MAX_LIMIT):
    try:
        limit = int(value)
    except Exception:
        limit = default
    return max(1, min(limit, max_limit))


def _normalize_offset(value):
    try:
        offset = int(value)
    except Exception:
        offset = 0
    return max(0, offset)


def _normalize_sort(value: str | None):
    raw = _normalize_text(value) or DEFAULT_SORT
    direction = "desc"
    field = raw

    if raw.startswith("-"):
        field = raw[1:]
        direction = "desc"
    elif "." in raw:
        parts = raw.split(".", 1)
        field = parts[0]
        direction = parts[1] if parts[1] in {"asc", "desc"} else "desc"
    elif raw.endswith("_asc"):
        field = raw[:-4]
        direction = "asc"
    elif raw.endswith("_desc"):
        field = raw[:-5]
        direction = "desc"

    if field not in SORTABLE_COLUMNS:
        field = "published"

    return field, direction


def _where_parts(search=None, sentiment=None, category=None, project_id=None, date_from=None, date_to=None, source_url=None, added_from=None, added_to=None):
    clauses = []
    params = []

    term = _normalize_text(search)
    if term:
        escaped = term.replace(",", " ").replace("%", "").replace("*", "")
        pattern = f"%{escaped}%"
        clauses.append(
            "("
            "title ilike %s or summary ilike %s or text ilike %s or "
            "source ilike %s or source_url ilike %s or author ilike %s"
            ")"
        )
        params.extend([pattern] * 6)

    sentiment_value = _normalize_sentiment(sentiment)
    if sentiment_value and sentiment_value != "all":
        clauses.append("sentiment = %s")
        params.append(sentiment_value)

    category_value = _normalize_category(category)
    if category_value and category_value != "all":
        clauses.append("category = %s")
        params.append(category_value)

    if project_id is not None:
        article_ids = list_article_ids_for_project(project_id)
        if not article_ids:
            clauses.append("id = -1")
        else:
            clauses.append("id = any(%s)")
            params.append(article_ids)

    source_url_value = _normalize_text(source_url)
    if source_url_value:
        clauses.append("lower(source_url) = %s")
        params.append(source_url_value.lower())

    date_from_value = _normalize_date_bound(date_from)
    if date_from_value:
        clauses.append("coalesce(published, created_at) >= %s")
        params.append(date_from_value)

    date_to_value = _normalize_date_bound(date_to)
    if date_to_value:
        clauses.append("coalesce(published, created_at) <= %s")
        params.append(date_to_value)

    added_from_value = _normalize_date_bound(added_from)
    if added_from_value:
        clauses.append("fetched_at >= %s")
        params.append(added_from_value)

    added_to_value = _normalize_date_bound(added_to)
    if added_to_value:
        clauses.append("fetched_at <= %s")
        params.append(added_to_value)

    if clauses:
        return " where " + " and ".join(clauses), params
    return "", params


def _fetch_articles(limit=None, offset=None, search=None, sentiment=None, category=None, project_id=None, order="published.desc", select=ARTICLES_SELECT, date_from=None, date_to=None, source_url=None, added_from=None, added_to=None, max_limit=MAX_LIMIT):
    if not config.DATABASE_URL:
        return [], 0

    field, direction = _normalize_sort(order)
    limit = _normalize_limit(limit, max_limit=max_limit)
    offset = _normalize_offset(offset)
    where_sql, params = _where_parts(
        search=search,
        sentiment=sentiment,
        category=category,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        source_url=source_url,
        added_from=added_from,
        added_to=added_to,
    )

    try:
        rows = db.fetch_all(
            f"""
            select {select}
            from articles
            {where_sql}
            order by {field} {direction}
            limit %s offset %s
            """,
            (*params, limit, offset),
        )
        count_row = db.fetch_one(
            f"""
            select count(*)::int as total
            from articles
            {where_sql}
            """,
            tuple(params),
        )
        total = int((count_row or {}).get("total") or len(rows))
        return rows, total
    except Exception:
        return [], 0


def _project_similarity_scores(project_id):
    """{article_id: score} for one project, or {} when there is nothing to
    attach. Split out so a streaming reader can look them up once up front
    instead of per page."""
    from services.projects.projects_store import list_article_similarity_scores_for_project

    if project_id is None:
        return {}
    return list_article_similarity_scores_for_project(project_id) or {}


def _apply_similarity_scores(rows, scores):
    if not scores:
        return rows
    for row in rows:
        try:
            article_id = int(row.get("id"))
        except Exception:
            continue
        if article_id in scores:
            row["project_similarity_score"] = scores[article_id]
    return rows


def _attach_project_similarity_scores(rows, project_id):
    if project_id is None or not rows:
        return rows
    return _apply_similarity_scores(rows, _project_similarity_scores(project_id))


def list_idea_clusters_for_project(project_id, limit=50, offset=0):
    """Paginated cross-article idea clusters for a project (see schema.sql's
    idea_clusters/idea_cluster_articles - the persisted, cross-run
    counterpart to analysis/aggregation.py's per-run in-memory rollup).

    Returns the empty page shape for a falsy project_id or on a database
    that hasn't had schema.sql re-run yet (idea_clusters doesn't exist),
    same defensive style as the rest of this module's DB calls.
    """
    limit = _normalize_limit(limit, default=50)
    offset = _normalize_offset(offset)
    empty = {"clusters": [], "total": 0, "limit": limit, "offset": offset}
    if not project_id or not config.DATABASE_URL:
        return empty
    try:
        rows = db.fetch_all(
            """
            select id, idea, type, category, frequency_estimate, first_seen_at, last_seen_at
            from idea_clusters
            where project_id = %s
            order by frequency_estimate desc, last_seen_at desc
            limit %s offset %s
            """,
            (int(project_id), limit, offset),
        )
        count_row = db.fetch_one(
            "select count(*)::int as total from idea_clusters where project_id = %s",
            (int(project_id),),
        )
    except Exception:
        return empty
    return {"clusters": rows, "total": int((count_row or {}).get("total") or 0), "limit": limit, "offset": offset}


def list_articles_for_idea_cluster(cluster_id, project_id, limit=10, offset=0):
    """Representative source articles for one idea cluster, scoped to the
    project it belongs to (so a cluster from a project the caller can't see
    can't be browsed by guessing its id). Returns None - distinct from the
    empty page shape - when the cluster doesn't exist or isn't in that
    project, so the caller can 404 instead of showing an empty result."""
    limit = _normalize_limit(limit, default=10, max_limit=500)
    offset = _normalize_offset(offset)
    if not config.DATABASE_URL:
        return None
    try:
        cluster = db.fetch_one(
            "select id from idea_clusters where id = %s and project_id = %s",
            (int(cluster_id), int(project_id)),
        )
        if not cluster:
            return None
        rows = db.fetch_all(
            """
            select a.id, a.url, a.title, a.source, a.published, a.summary, a.sentiment, a.pipeline_run_id
            from articles a
            join idea_cluster_articles ica on ica.article_id = a.id
            where ica.idea_cluster_id = %s
            order by a.published desc nulls last, a.created_at desc
            limit %s offset %s
            """,
            (int(cluster_id), limit, offset),
        )
        count_row = db.fetch_one(
            "select count(*)::int as total from idea_cluster_articles where idea_cluster_id = %s",
            (int(cluster_id),),
        )
    except Exception:
        return None
    return {"articles": rows, "total": int((count_row or {}).get("total") or 0), "limit": limit, "offset": offset}


def get_analysis_status_counts(project_id=None):
    """Article counts grouped by analysis_status (pending/processing/success/
    failed/partial), optionally scoped to a project - lets an operator see
    how many articles need reprocessing. {} on a database that hasn't had
    schema.sql re-run yet (analysis_status doesn't exist).
    """
    if not config.DATABASE_URL:
        return {}
    try:
        if project_id is not None:
            rows = db.fetch_all(
                """
                select a.analysis_status, count(*)::int as total
                from articles a
                join article_projects ap on ap.article_id = a.id
                where ap.project_id = %s
                group by a.analysis_status
                """,
                (int(project_id),),
            )
        else:
            rows = db.fetch_all(
                "select analysis_status, count(*)::int as total from articles group by analysis_status"
            )
        return {(row.get("analysis_status") or "unknown"): int(row.get("total") or 0) for row in rows or []}
    except Exception:
        return {}


def list_analysis_errors(project_id=None, limit=24, offset=0):
    """Paginated list of articles whose most recent analysis run failed
    (analysis_status = 'failed'), with the stored analysis_error. Empty page
    on a database that hasn't had schema.sql re-run yet."""
    limit = _normalize_limit(limit)
    offset = _normalize_offset(offset)
    empty = {"errors": [], "total": 0, "limit": limit, "offset": offset}
    if not config.DATABASE_URL:
        return empty

    where = "where a.analysis_status = 'failed'"
    params = []
    if project_id is not None:
        where += " and exists (select 1 from article_projects ap where ap.article_id = a.id and ap.project_id = %s)"
        params.append(int(project_id))

    try:
        rows = db.fetch_all(
            f"""
            select a.id, a.url, a.title, a.source, a.published, a.analysis_error,
                   a.analysis_attempt_count, a.analysis_started_at, a.analysis_finished_at
            from articles a
            {where}
            order by a.analysis_finished_at desc nulls last
            limit %s offset %s
            """,
            (*params, limit, offset),
        )
        count_row = db.fetch_one(f"select count(*)::int as total from articles a {where}", tuple(params))
    except Exception:
        return empty
    return {"errors": rows, "total": int((count_row or {}).get("total") or 0), "limit": limit, "offset": offset}


_ARTICLE_ANALYSIS_BASE_COLUMNS = (
    "id", "url", "title", "source", "published", "sentiment", "article_category",
    "writer_tone", "article_tone", "insight_json", "analyzed_at", "analysis_model",
    "analysis_prompt_version",
)

_ARTICLE_ANALYSIS_METADATA_COLUMNS = (
    "sentiment_score", "sentiment_low_confidence", "sentiment_model",
    "category_confidence", "writer_tone_confidence", "article_tone_confidence",
    "classification_model", "extraction_model", "analysis_pipeline_version",
    "source_language", "source_language_confidence", "embedding_dimensions",
    "analysis_status", "analysis_error", "analysis_started_at", "analysis_finished_at",
    "analysis_attempt_count", "reprocess_requested_at",
)


@lru_cache(maxsize=1)
def _live_articles_columns():
    if not config.DATABASE_URL:
        return frozenset()
    try:
        rows = db.fetch_all(
            """
            select column_name from information_schema.columns
            where table_schema = 'public' and table_name = 'articles'
            """
        )
        return frozenset(row.get("column_name") for row in rows or [] if row.get("column_name"))
    except Exception:
        return frozenset()


def _article_analysis_select_columns():
    live = _live_articles_columns()
    metadata_columns = [c for c in _ARTICLE_ANALYSIS_METADATA_COLUMNS if c in live] if live else []
    return list(_ARTICLE_ANALYSIS_BASE_COLUMNS) + metadata_columns


def _shape_article_analysis(row: dict) -> dict:
    """Normalize one articles row into the analysis-detail response shape -
    the single source of truth for what GET .../analysis returns, so a
    malformed insight_json (wrong type, not a dict) never leaks through as
    if it were real content."""
    insight = row.get("insight_json") if isinstance(row.get("insight_json"), dict) else {}
    writer_tone = _normalize_tone(row.get("writer_tone"))
    article_tone = _normalize_tone(row.get("article_tone"))
    from services.articles.articles_analytics import compute_overall_tone

    return {
        "article_id": row.get("id"),
        "url": row.get("url"),
        "title": row.get("title"),
        "source": row.get("source"),
        "published": row.get("published"),
        "sentiment": _normalize_sentiment(row.get("sentiment")) or "neutral",
        "article_category": _normalize_article_category(row.get("article_category")),
        "writer_tone": writer_tone,
        "article_tone": article_tone,
        "overall_tone": compute_overall_tone(article_tone, writer_tone),
        "summary": _normalize_text(insight.get("summary")),
        "insight_json": insight,
        "analysis_status": row.get("analysis_status") or "success",
        "analysis_error": row.get("analysis_error"),
        "analyzed_at": row.get("analyzed_at"),
        "analysis_model": row.get("analysis_model"),
        "analysis_pipeline_version": row.get("analysis_pipeline_version") or row.get("analysis_prompt_version"),
        "confidence": {
            "sentiment": row.get("sentiment_score"),
            "sentiment_low_confidence": bool(row.get("sentiment_low_confidence")),
            "category": row.get("category_confidence"),
            "writer_tone": row.get("writer_tone_confidence"),
            "article_tone": row.get("article_tone_confidence"),
        },
        "source_language": row.get("source_language"),
        "source_language_confidence": row.get("source_language_confidence"),
        "models": {
            "sentiment": row.get("sentiment_model"),
            "classification": row.get("classification_model"),
            "extraction": row.get("extraction_model"),
        },
        "processing": {
            "attempt_count": row.get("analysis_attempt_count"),
            "started_at": row.get("analysis_started_at"),
            "finished_at": row.get("analysis_finished_at"),
            "reprocess_requested_at": row.get("reprocess_requested_at"),
        },
    }


def get_article_analysis(article_id):
    """Full analysis detail for one article - the response shape GET
    /api/articles/{id}/analysis returns. None if the article doesn't exist
    (or the database is unreachable), so the route can 404 rather than
    return a half-filled body."""
    if not config.DATABASE_URL:
        return None
    columns = _article_analysis_select_columns()
    try:
        row = db.fetch_one(
            f"select {', '.join(columns)} from articles where id = %s",
            (int(article_id),),
        )
    except Exception:
        return None
    if not row:
        return None
    return _shape_article_analysis(row)
