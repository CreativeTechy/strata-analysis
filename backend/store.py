"""The SAVER stage: direct Postgres upsert helpers for enriched articles."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import json

import config
import db
from embeddings import cosine_similarity
from projects_store import list_project_ids_for_source_url, list_projects, set_article_projects
from psycopg.types.json import Jsonb

ARTICLE_COLUMNS = (
    "url", "source", "source_url", "title", "author", "published", "text",
    "fetched_at", "summary", "sentiment", "relevance_score", "category",
    "article_category", "insight_json", "analysis_model", "analysis_prompt_version", "analyzed_at",
    "organizations", "entities", "topics", "key_points", "risks", "opportunities",
    "brands", "car_models", "embedding_json", "embedding_model", "embedding_source", "embedded_at",
)

LEGACY_ARTICLE_COLUMNS = (
    "url", "source", "source_url", "title", "author", "published", "text",
    "fetched_at", "summary", "sentiment", "relevance_score", "category",
    "organizations", "entities", "topics", "key_points", "risks", "opportunities",
    "brands", "car_models",
)

ARTICLE_MUTABLE_FIELDS = (
    "url",
    "source",
    "source_url",
    "title",
    "author",
    "published",
    "text",
    "fetched_at",
    "summary",
    "sentiment",
    "relevance_score",
    "category",
    "article_category",
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


def _row(article):
    return {k: article.get(k) for k in ARTICLE_COLUMNS}


def _legacy_row(article):
    return {k: article.get(k) for k in LEGACY_ARTICLE_COLUMNS}


def _log_db_error(prefix, error):
    print(f"{prefix}: {error}")


def _jsonb_param(value):
    if value is None:
        value = []
    return Jsonb(value)


def _null_if_blank(value):
    text = str(value).strip() if value is not None else ""
    return text or None


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


def _article_returning_sql():
    columns = _article_columns()
    returning = ["id", "source_url"]
    if "embedding_json" in columns:
        returning.append("embedding_json")
    return ", ".join(returning)


def _article_row(article):
    row = _row(article)
    fields = _article_write_fields()
    params = []
    for field in fields:
        value = row[field]
        if field in ARTICLE_JSON_FIELDS:
            value = _jsonb_param(value)
        elif field in {"fetched_at", "analyzed_at", "embedded_at"}:
            value = _null_if_blank(value)
        params.append(value)
    return fields, tuple(params)


def _upsert_article_row(article):
    fields, params = _article_row(article)
    if not fields:
        return None
    columns_sql = ", ".join(fields)
    values_sql = ", ".join(["%s"] * len(fields))
    returning_sql = _article_returning_sql()
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
            updates=", ".join(f"{field} = excluded.{field}" for field in fields if field != "url"),
            returning=returning_sql,
        ),
        params,
    )


def save_articles(articles, batch_size=50):
    if not config.DATABASE_URL:
        print("Database credentials not set, skipping upload.")
        return 0

    sent = 0
    project_id = None
    try:
        from os import environ

        raw_project_id = (environ.get("PIPELINE_PROJECT_ID") or "").strip()
        if raw_project_id:
            project_id = int(raw_project_id)
    except Exception:
        project_id = None

    source_project_cache = {}
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
                row = _upsert_article_row(article)
                if row:
                    persisted.append((article, row))
                    sent += 1

            for article, row in persisted:
                if not isinstance(row, dict):
                    continue
                try:
                    article_id = int(row.get("id"))
                except Exception:
                    continue
                source_url = (row.get("source_url") or article.get("source_url") or "").strip()
                if not source_url:
                    continue
                if source_url not in source_project_cache:
                    source_project_cache[source_url] = list_project_ids_for_source_url(source_url)
                project_ids = list(source_project_cache.get(source_url) or [])
                if project_id is not None and project_id not in project_ids:
                    project_ids.append(project_id)
                for linked_project_id in project_ids:
                    linked_articles[linked_project_id].add(article_id)

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
                    if best_project_id is not None and best_score >= 0.78:
                        linked_articles[best_project_id].add(article_id)
                        linked_scores[best_project_id][article_id] = best_score
            print(f"  Uploaded batch {i // batch_size + 1} ({len(source_batch)} articles)")
        except Exception as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code == 400:
                try:
                    legacy_batch = [_legacy_row(a) for a in source_batch]
                    persisted = []
                    for article in source_batch:
                        row = db.fetch_one(
                            """
                            insert into articles (
                                url, source, source_url, title, author, published, text,
                                fetched_at, summary, sentiment, relevance_score, category,
                                organizations, entities, topics, key_points, risks, opportunities,
                                brands, car_models
                            )
                            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            on conflict (url) do update set
                                source = excluded.source,
                                source_url = excluded.source_url,
                                title = excluded.title,
                                author = excluded.author,
                                published = excluded.published,
                                text = excluded.text,
                                fetched_at = excluded.fetched_at,
                                summary = excluded.summary,
                                sentiment = excluded.sentiment,
                                relevance_score = excluded.relevance_score,
                                category = excluded.category,
                                organizations = excluded.organizations,
                                entities = excluded.entities,
                                topics = excluded.topics,
                                key_points = excluded.key_points,
                                risks = excluded.risks,
                                opportunities = excluded.opportunities,
                                brands = excluded.brands,
                                car_models = excluded.car_models
                            returning id, source_url
                            """,
                            (
                                _legacy_row(article)["url"],
                                _legacy_row(article)["source"],
                                _legacy_row(article)["source_url"],
                                _legacy_row(article)["title"],
                                _legacy_row(article)["author"],
                                _legacy_row(article)["published"],
                                _legacy_row(article)["text"],
                                _null_if_blank(_legacy_row(article)["fetched_at"]),
                                _legacy_row(article)["summary"],
                                _legacy_row(article)["sentiment"],
                                _legacy_row(article)["relevance_score"],
                                _legacy_row(article)["category"],
                                _jsonb_param(_legacy_row(article)["organizations"]),
                                _jsonb_param(_legacy_row(article)["entities"]),
                                _jsonb_param(_legacy_row(article)["topics"]),
                                _jsonb_param(_legacy_row(article)["key_points"]),
                                _jsonb_param(_legacy_row(article)["risks"]),
                                _jsonb_param(_legacy_row(article)["opportunities"]),
                                _jsonb_param(_legacy_row(article)["brands"]),
                                _jsonb_param(_legacy_row(article)["car_models"]),
                            ),
                        )
                        if row:
                            persisted.append((article, row))
                    sent += len(legacy_batch)
                    print(
                        f"  Uploaded batch {i // batch_size + 1} ({len(legacy_batch)} articles) using legacy article schema fallback"
                    )
                    continue
                except Exception as legacy_error:
                    _log_db_error(f"  Database upload error for batch {i // batch_size + 1}", legacy_error)
                    continue
            _log_db_error(f"  Database upload error for batch {i // batch_size + 1}", e)

    if linked_articles:
        for linked_project_id, article_ids in linked_articles.items():
            set_article_projects(sorted(article_ids), linked_project_id, similarity_scores=linked_scores.get(linked_project_id, {}))

    return sent


def delete_all_articles():
    if not config.DATABASE_URL:
        print("Database credentials not set, skipping article delete.")
        return 0

    try:
        db.execute("delete from articles")
        return 1
    except Exception as e:
        _log_db_error("  article delete error", e)
        return 0
