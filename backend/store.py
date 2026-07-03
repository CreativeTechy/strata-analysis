"""The SAVER stage: direct Postgres upsert helpers for enriched articles."""

from __future__ import annotations

from collections import defaultdict
import json

import config
import db
from embeddings import cosine_similarity
from events_store import list_event_ids_for_feed_url, list_events, set_article_events

ARTICLE_COLUMNS = (
    "url", "source", "feed", "title", "author", "published", "text",
    "fetched_at", "summary", "sentiment", "relevance_score", "category",
    "article_category", "insight_json", "analysis_model", "analysis_prompt_version", "analyzed_at",
    "organizations", "entities", "topics", "key_points", "risks", "opportunities",
    "brands", "car_models", "embedding_json", "embedding_model", "embedding_source", "embedded_at",
)

LEGACY_ARTICLE_COLUMNS = (
    "url", "source", "feed", "title", "author", "published", "text",
    "fetched_at", "summary", "sentiment", "relevance_score", "category",
    "organizations", "entities", "topics", "key_points", "risks", "opportunities",
    "brands", "car_models",
)

CRAWL_COLUMNS = (
    "crawl_id", "url", "source", "seed", "title", "text", "words", "depth", "fetched_at",
)


def _row(article):
    return {k: article.get(k) for k in ARTICLE_COLUMNS}


def _legacy_row(article):
    return {k: article.get(k) for k in LEGACY_ARTICLE_COLUMNS}


def _response_snippet(payload, limit=500):
    try:
        if isinstance(payload, (dict, list)):
            return json.dumps(payload, ensure_ascii=False)[:limit]
        return str(payload or "")[:limit]
    except Exception:
        return ""


def _log_db_error(prefix, error):
    print(f"{prefix}: {error}")


def _upsert_article_row(article):
    row = _row(article)
    return db.fetch_one(
        """
        insert into articles (
            url, source, feed, title, author, published, text,
            fetched_at, summary, sentiment, relevance_score, category,
            article_category, insight_json, analysis_model, analysis_prompt_version, analyzed_at,
            organizations, entities, topics, key_points, risks, opportunities,
            brands, car_models, embedding_json, embedding_model, embedding_source, embedded_at
        )
        values (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )
        on conflict (url) do update set
            source = excluded.source,
            feed = excluded.feed,
            title = excluded.title,
            author = excluded.author,
            published = excluded.published,
            text = excluded.text,
            fetched_at = excluded.fetched_at,
            summary = excluded.summary,
            sentiment = excluded.sentiment,
            relevance_score = excluded.relevance_score,
            category = excluded.category,
            article_category = excluded.article_category,
            insight_json = excluded.insight_json,
            analysis_model = excluded.analysis_model,
            analysis_prompt_version = excluded.analysis_prompt_version,
            analyzed_at = excluded.analyzed_at,
            organizations = excluded.organizations,
            entities = excluded.entities,
            topics = excluded.topics,
            key_points = excluded.key_points,
            risks = excluded.risks,
            opportunities = excluded.opportunities,
            brands = excluded.brands,
            car_models = excluded.car_models,
            embedding_json = excluded.embedding_json,
            embedding_model = excluded.embedding_model,
            embedding_source = excluded.embedding_source,
            embedded_at = excluded.embedded_at
        returning id, feed, embedding_json
        """,
        (
            row["url"], row["source"], row["feed"], row["title"], row["author"], row["published"], row["text"],
            row["fetched_at"], row["summary"], row["sentiment"], row["relevance_score"], row["category"],
            row["article_category"], row["insight_json"], row["analysis_model"], row["analysis_prompt_version"], row["analyzed_at"],
            row["organizations"], row["entities"], row["topics"], row["key_points"], row["risks"], row["opportunities"],
            row["brands"], row["car_models"], row["embedding_json"], row["embedding_model"], row["embedding_source"], row["embedded_at"],
        ),
    )


def save_crawl_pages(rows, batch_size=50):
    if not config.DATABASE_URL:
        print("Database credentials not set, skipping crawl save.")
        return 0

    sent = 0
    for i in range(0, len(rows), batch_size):
        batch = [{k: r.get(k) for k in CRAWL_COLUMNS} for r in rows[i:i + batch_size]]
        try:
            for row in batch:
                db.execute(
                    """
                    insert into crawl_pages (crawl_id, url, source, seed, title, text, words, depth, fetched_at)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (url) do update set
                      crawl_id = excluded.crawl_id,
                      source = excluded.source,
                      seed = excluded.seed,
                      title = excluded.title,
                      text = excluded.text,
                      words = excluded.words,
                      depth = excluded.depth,
                      fetched_at = excluded.fetched_at
                    """,
                    (
                        row["crawl_id"], row["url"], row["source"], row["seed"], row["title"],
                        row["text"], row["words"], row["depth"], row["fetched_at"],
                    ),
                )
            sent += len(batch)
        except Exception as e:
            _log_db_error(f"  crawl_pages upload error for batch {i // batch_size + 1}", e)
    return sent


def save_articles(articles, batch_size=50):
    if not config.DATABASE_URL:
        print("Database credentials not set, skipping upload.")
        return 0

    sent = 0
    event_id = None
    try:
        from os import environ

        raw_event_id = (environ.get("PIPELINE_EVENT_ID") or "").strip()
        if raw_event_id:
            event_id = int(raw_event_id)
    except Exception:
        event_id = None

    feed_event_cache = {}
    linked_articles = defaultdict(set)
    linked_scores = defaultdict(dict)
    event_embedding_cache = None
    event_embedding_map = {}

    def _load_event_embedding_map():
        nonlocal event_embedding_cache, event_embedding_map
        if event_embedding_cache is not None:
            return event_embedding_map

        event_embedding_cache = list_events()
        event_embedding_map = {}
        for event in event_embedding_cache or []:
            try:
                event_id_value = int(event.get("id"))
            except Exception:
                continue
            embedding = event.get("embedding_json") or []
            if isinstance(embedding, list) and embedding:
                event_embedding_map[event_id_value] = embedding
        return event_embedding_map

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
                feed_url = (row.get("feed") or article.get("feed") or "").strip()
                if not feed_url:
                    continue
                if feed_url not in feed_event_cache:
                    feed_event_cache[feed_url] = list_event_ids_for_feed_url(feed_url)
                event_ids = list(feed_event_cache.get(feed_url) or [])
                if event_id is not None and event_id not in event_ids:
                    event_ids.append(event_id)
                for linked_event_id in event_ids:
                    linked_articles[linked_event_id].add(article_id)

                article_embedding = article.get("embedding_json") or row.get("embedding_json") or []
                if isinstance(article_embedding, list) and article_embedding:
                    event_embeddings = _load_event_embedding_map()
                    best_event_id = None
                    best_score = 0.0
                    for candidate_event_id, candidate_embedding in event_embeddings.items():
                        score = cosine_similarity(article_embedding, candidate_embedding)
                        if score > best_score:
                            best_score = score
                            best_event_id = candidate_event_id
                    if best_event_id is not None and best_score >= 0.78:
                        linked_articles[best_event_id].add(article_id)
                        linked_scores[best_event_id][article_id] = best_score
            print(f"  Uploaded batch {i // batch_size + 1} ({len(source_batch)} articles)")
        except Exception as e:
            _log_db_error(f"  Database upload error for batch {i // batch_size + 1}", e)

    if linked_articles:
        for linked_event_id, article_ids in linked_articles.items():
            set_article_events(sorted(article_ids), linked_event_id, similarity_scores=linked_scores.get(linked_event_id, {}))

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
