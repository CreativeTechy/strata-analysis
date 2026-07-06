"""Postgres-backed event helpers."""

from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from typing import Iterable
from urllib.parse import unquote, urlparse, urlunparse

import config
import db
from embeddings import build_event_embedding_text, get_embedding
from psycopg.types.json import Jsonb


EVENT_SELECT = (
    "id,name,status,description,location,target_audience,hashtags,keywords,usernames,"
    "start_date,end_date,embedding_json,embedding_model,embedding_source,embedded_at,created_at,updated_at"
)

EVENT_SELECT_FIELDS = tuple(EVENT_SELECT.split(","))
EVENT_MUTABLE_FIELDS = (
    "name",
    "status",
    "description",
    "location",
    "target_audience",
    "hashtags",
    "keywords",
    "usernames",
    "start_date",
    "end_date",
)
EVENT_EMBEDDING_FIELDS = ("embedding_json", "embedding_model", "embedding_source", "embedded_at")


@lru_cache(maxsize=1)
def _event_table_columns():
    if not config.DATABASE_URL:
        return set()

    try:
        rows = db.fetch_all(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'events'
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


def _event_columns():
    columns = _event_table_columns()
    if columns:
        return columns
    return set(EVENT_SELECT_FIELDS)


def _event_select_sql():
    columns = _event_columns()
    selected = [field for field in EVENT_SELECT_FIELDS if field in columns]
    return ",".join(selected or ["id", "name", "status", "start_date", "end_date", "created_at", "updated_at"])


def _event_write_fields():
    columns = _event_columns()
    return [field for field in EVENT_MUTABLE_FIELDS if field in columns]


def _event_embedding_fields():
    columns = _event_columns()
    return [field for field in EVENT_EMBEDDING_FIELDS if field in columns]


def _jsonb_param(value):
    return Jsonb(value if value is not None else [])


def _normalize_url(value):
    text = str(value or "").strip()
    if not text:
        return ""

    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        path = unquote(parsed.path or "").rstrip("/")
        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                path,
                parsed.params or "",
                parsed.query or "",
                parsed.fragment or "",
            )
        )

    return text.rstrip("/")


def _clean_ids(values: Iterable) -> list[int]:
    cleaned = []
    seen = set()
    for value in values or []:
        try:
            item = int(value)
        except Exception:
            continue
        if item not in seen:
            seen.add(item)
            cleaned.append(item)
    return cleaned


def _clean_terms(values: Iterable) -> list[str]:
    cleaned = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _normalize_event(row, feed_ids=None):
    row = row or {}
    hashtags = row.get("hashtags") or []
    keywords = row.get("keywords") or []
    usernames = row.get("usernames") or []
    if isinstance(hashtags, str):
        hashtags = [hashtags]
    if isinstance(keywords, str):
        keywords = [keywords]
    if isinstance(usernames, str):
        usernames = [usernames]
    return {
        "id": row.get("id"),
        "name": (row.get("name") or "").strip(),
        "status": (row.get("status") or "draft").strip().lower() or "draft",
        "description": (row.get("description") or "").strip(),
        "location": (row.get("location") or "").strip(),
        "target_audience": (row.get("target_audience") or "").strip(),
        "hashtags": _clean_terms(hashtags),
        "keywords": _clean_terms(keywords),
        "usernames": _clean_terms(usernames),
        "start_date": row.get("start_date"),
        "end_date": row.get("end_date"),
        "embedding_json": row.get("embedding_json") or [],
        "embedding_model": (row.get("embedding_model") or "").strip(),
        "embedding_source": (row.get("embedding_source") or "").strip(),
        "embedded_at": row.get("embedded_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "feed_ids": _clean_ids(feed_ids or []),
    }


def _normalize_feed(row):
    url = (row.get("url") or "").strip()
    name = (row.get("name") or "").strip() or url
    inferred_type = config._infer_source_type(url)
    source_type = (row.get("source_type") or inferred_type or "rss").strip().lower() or "rss"
    if inferred_type == "social":
        source_type = "social"
    return {
        "id": row.get("id"),
        "url": url,
        "name": name,
        "enabled": bool(row.get("enabled", True)),
        "source_type": source_type,
        "category": (row.get("category") or "").strip(),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _fetch_rows(query, params=None):
    if not config.DATABASE_URL:
        return []
    try:
        return db.fetch_all(query, params or ())
    except Exception:
        return []


def _fetch_event_feed_map():
    rows = _fetch_rows("select event_id, feed_id from event_feeds order by event_id asc, feed_id asc")
    mapping = defaultdict(list)
    for row in rows:
        try:
            event_id = int(row.get("event_id"))
            feed_id = int(row.get("feed_id"))
        except Exception:
            continue
        mapping[event_id].append(feed_id)
    return mapping


def _fetch_feed_event_map():
    rows = _fetch_rows("select event_id, feed_id from event_feeds order by feed_id asc, event_id asc")
    mapping = defaultdict(list)
    for row in rows:
        try:
            event_id = int(row.get("event_id"))
            feed_id = int(row.get("feed_id"))
        except Exception:
            continue
        mapping[feed_id].append(event_id)
    return mapping


def _fetch_feed_url_map():
    rows = _fetch_rows("select id, url from feeds order by id asc")
    mapping = defaultdict(list)
    for row in rows:
        try:
            feed_id = int(row.get("id"))
        except Exception:
            continue
        key = _normalize_url(row.get("url"))
        if key:
            mapping[key].append(feed_id)
    return mapping


def _fetch_article_event_map(event_id):
    rows = _fetch_rows(
        "select article_id from article_events where event_id = %s order by article_id asc",
        (int(event_id),),
    )
    ids = []
    seen = set()
    for row in rows:
        try:
            article_id = int(row.get("article_id"))
        except Exception:
            continue
        if article_id not in seen:
            seen.add(article_id)
            ids.append(article_id)
    return ids


def _persist_event_embedding(event):
    if not config.DATABASE_URL:
        return {}

    embedding_fields = _event_embedding_fields()
    if not embedding_fields:
        return {}

    text = build_event_embedding_text(event)
    if not text:
        return {}

    embedding = get_embedding(text)
    if not embedding:
        return {}

    try:
        event_id = int(event.get("id"))
    except Exception:
        return {}

    try:
        assignments = []
        params = []
        if "embedding_json" in embedding_fields:
            assignments.append("embedding_json = %s")
            params.append(_jsonb_param(embedding.get("embedding_json") or []))
        if "embedding_model" in embedding_fields:
            assignments.append("embedding_model = %s")
            params.append(embedding.get("embedding_model") or "")
        if "embedding_source" in embedding_fields:
            assignments.append("embedding_source = %s")
            params.append(embedding.get("embedding_source") or "")
        if "embedded_at" in embedding_fields:
            assignments.append("embedded_at = %s")
            params.append(embedding.get("embedded_at"))
        if not assignments:
            return {}
        assignments.append("updated_at = now()")
        params.append(event_id)
        row = db.fetch_one(
            f"""
            update events
            set {", ".join(assignments)}
            where id = %s
            returning {_event_select_sql()}
            """,
            params,
        )
        if isinstance(row, dict):
            return {
                "embedding_json": row.get("embedding_json") or embedding.get("embedding_json") or [],
                "embedding_model": (row.get("embedding_model") or embedding.get("embedding_model") or "").strip(),
                "embedding_source": (row.get("embedding_source") or embedding.get("embedding_source") or "").strip(),
                "embedded_at": row.get("embedded_at") or embedding.get("embedded_at"),
            }
    except Exception:
        return embedding

    return embedding


def list_events():
    if not config.DATABASE_URL:
        return []

    try:
        rows = db.fetch_all(
            f"""
            select {_event_select_sql()}
            from events
            order by created_at asc
            """
        )
        feed_map = _fetch_event_feed_map()
        return [_normalize_event(row, feed_map.get(row.get("id"), [])) for row in rows]
    except Exception:
        return []


def list_events_page(limit=25, offset=0):
    if not config.DATABASE_URL:
        return {"events": [], "total": 0, "limit": int(limit or 0), "offset": int(offset or 0)}

    limit = max(1, min(int(limit or 25), 100))
    offset = max(0, int(offset or 0))

    try:
        rows = db.fetch_all(
            f"""
            select {_event_select_sql()}
            from events
            order by created_at asc
            limit %s offset %s
            """,
            (limit, offset),
        )
        total_row = db.fetch_one("select count(*)::int as total from events")
        feed_map = _fetch_event_feed_map()
        events = [_normalize_event(row, feed_map.get(row.get("id"), [])) for row in rows if isinstance(row, dict)]
        total = int((total_row or {}).get("total") or len(events))
        return {"events": events, "total": total, "limit": limit, "offset": offset}
    except Exception:
        return {"events": [], "total": 0, "limit": limit, "offset": offset}


def get_event(event_id):
    if not config.DATABASE_URL:
        return None

    try:
        rows = db.fetch_all(
            f"""
            select {_event_select_sql()}
            from events
            where id = %s
            limit 1
            """,
            (int(event_id),),
        )
        if not rows:
            return None
        feed_map = _fetch_event_feed_map()
        return _normalize_event(rows[0], feed_map.get(rows[0].get("id"), []))
    except Exception:
        return None


def _event_payload(event):
    if not isinstance(event, dict):
        event = {}

    hashtags = event.get("hashtags")
    keywords = event.get("keywords")
    usernames = event.get("usernames")
    if isinstance(hashtags, str):
        hashtags = [part.strip() for part in hashtags.replace("\n", ",").split(",")]
    if isinstance(keywords, str):
        keywords = [part.strip() for part in keywords.replace("\n", ",").split(",")]
    if isinstance(usernames, str):
        usernames = [part.strip() for part in usernames.replace("\n", ",").split(",")]

    return {
        "name": (event.get("name") or "").strip(),
        "status": (event.get("status") or "draft").strip().lower() or "draft",
        "description": (event.get("description") or "").strip() or None,
        "location": (event.get("location") or "").strip() or None,
        "target_audience": (event.get("target_audience") or "").strip() or None,
        "hashtags": _clean_terms(hashtags or []),
        "keywords": _clean_terms(keywords or []),
        "usernames": _clean_terms(usernames or []),
        "start_date": event.get("start_date") or None,
        "end_date": event.get("end_date") or None,
    }


def _set_event_feeds(event_id, feed_ids):
    event_id = int(event_id)
    feed_ids = _clean_ids(feed_ids)
    try:
        db.execute("delete from event_feeds where event_id = %s", (event_id,))
        for feed_id in feed_ids:
            db.execute(
                """
                insert into event_feeds (event_id, feed_id)
                values (%s, %s)
                on conflict (event_id, feed_id) do nothing
                """,
                (event_id, feed_id),
            )
        return feed_ids
    except Exception:
        return []


def create_event(event):
    if not config.DATABASE_URL:
        return None

    payload = _event_payload(event)
    if not payload["name"]:
        return None

    feed_ids = _clean_ids(event.get("feed_ids") or [])
    try:
        write_fields = _event_write_fields()
        if not write_fields:
            return None
        insert_columns = ", ".join(write_fields)
        insert_values = ", ".join(["%s"] * len(write_fields))
        params = [
            _jsonb_param(payload[field]) if field in {"hashtags", "keywords", "usernames"} else payload[field]
            for field in write_fields
        ]
        row = db.fetch_one(
            f"""
            insert into events ({insert_columns})
            values ({insert_values})
            returning {_event_select_sql()}
            """,
            params,
        )
        if not row:
            return None
        created = _normalize_event(row)
        created.update(_persist_event_embedding(created))
        if feed_ids:
            created["feed_ids"] = set_event_feeds(created["id"], feed_ids)
        else:
            created["feed_ids"] = []
        return created
    except Exception as e:
        raise RuntimeError(f"Database request failed: {e}") from e


def update_event(event_id, event):
    if not config.DATABASE_URL:
        return None

    payload = _event_payload(event)
    feed_ids = event.get("feed_ids") if isinstance(event, dict) else None
    try:
        write_fields = _event_write_fields()
        if not write_fields:
            return None
        assignments = ", ".join(f"{field} = %s" for field in write_fields)
        params = [
            _jsonb_param(payload[field]) if field in {"hashtags", "keywords", "usernames"} else payload[field]
            for field in write_fields
        ]
        params.append(int(event_id))
        row = db.fetch_one(
            f"""
            update events
            set {assignments},
                updated_at = now()
            where id = %s
            returning {_event_select_sql()}
            """,
            params,
        )
        if not row:
            return None
        normalized = _normalize_event(row)
        normalized.update(_persist_event_embedding(normalized))
        if feed_ids is not None:
            normalized["feed_ids"] = _set_event_feeds(event_id, feed_ids)
        else:
            normalized["feed_ids"] = list_event_feed_ids(event_id)
        return normalized
    except Exception as e:
        raise RuntimeError(f"Database request failed: {e}") from e


def delete_event(event_id):
    if not config.DATABASE_URL:
        return False

    try:
        db.execute("delete from events where id = %s", (int(event_id),))
        return True
    except Exception:
        return False


def list_event_feed_ids(event_id):
    if not config.DATABASE_URL:
        return []

    try:
        rows = _fetch_rows(
            "select feed_id from event_feeds where event_id = %s order by feed_id asc",
            (int(event_id),),
        )
        ids = []
        seen = set()
        for row in rows:
            try:
                feed_id = int(row.get("feed_id"))
            except Exception:
                continue
            if feed_id not in seen:
                seen.add(feed_id)
                ids.append(feed_id)
        return ids
    except Exception:
        return []


def list_feed_event_ids(feed_id):
    if not config.DATABASE_URL:
        return []

    try:
        rows = _fetch_rows(
            "select event_id from event_feeds where feed_id = %s order by event_id asc",
            (int(feed_id),),
        )
        ids = []
        seen = set()
        for row in rows:
            try:
                event_id = int(row.get("event_id"))
            except Exception:
                continue
            if event_id not in seen:
                seen.add(event_id)
                ids.append(event_id)
        return ids
    except Exception:
        return []


def set_event_feeds(event_id, feed_ids):
    if not config.DATABASE_URL:
        return []
    return _set_event_feeds(event_id, feed_ids)


def set_feed_events(feed_id, event_ids):
    if not config.DATABASE_URL:
        return []

    feed_id = int(feed_id)
    event_ids = _clean_ids(event_ids)
    try:
        db.execute("delete from event_feeds where feed_id = %s", (feed_id,))
        for event_id in event_ids:
            db.execute(
                """
                insert into event_feeds (event_id, feed_id)
                values (%s, %s)
                on conflict (event_id, feed_id) do nothing
                """,
                (event_id, feed_id),
            )
        return event_ids
    except Exception:
        return []


def list_feeds_for_event(event_id):
    if not config.DATABASE_URL:
        return []

    try:
        rows = _fetch_rows(
            """
            select f.id, f.url, f.name, f.enabled, f.source_type, f.category, f.created_at, f.updated_at
            from feeds f
            inner join event_feeds ef on ef.feed_id = f.id
            where ef.event_id = %s
            order by f.created_at asc
            """,
            (int(event_id),),
        )
        return [_normalize_feed(row) for row in rows]
    except Exception:
        return []


def set_article_events(article_ids, event_id, similarity_scores=None):
    if not config.DATABASE_URL:
        return 0

    article_ids = _clean_ids(article_ids)
    if not article_ids:
        return 0

    event_id = int(event_id)
    score_map = {}
    if isinstance(similarity_scores, dict):
        for key, value in similarity_scores.items():
            try:
                article_key = int(key)
            except Exception:
                continue
            try:
                score_map[article_key] = float(value)
            except Exception:
                continue

    try:
        db.execute("delete from article_events where event_id = %s and article_id = any(%s)", (event_id, article_ids))
        for article_id in article_ids:
            db.execute(
                """
                insert into article_events (article_id, event_id, similarity_score)
                values (%s, %s, %s)
                on conflict (article_id, event_id) do update
                set similarity_score = excluded.similarity_score,
                    created_at = article_events.created_at
                """,
                (article_id, event_id, score_map.get(article_id)),
            )
        return len(article_ids)
    except Exception:
        return 0


def list_article_similarity_scores_for_event(event_id):
    if not config.DATABASE_URL:
        return {}

    try:
        rows = _fetch_rows(
            "select article_id, similarity_score from article_events where event_id = %s order by article_id asc",
            (int(event_id),),
        )
    except Exception:
        return {}

    scores = {}
    for row in rows:
        try:
            article_id = int(row.get("article_id"))
        except Exception:
            continue
        try:
            scores[article_id] = float(row.get("similarity_score"))
        except Exception:
            continue
    return scores


def list_article_ids_for_event(event_id):
    if not config.DATABASE_URL:
        return []

    ids = []
    seen = set()

    for article_id in _fetch_article_event_map(event_id):
        if article_id in seen:
            continue
        seen.add(article_id)
        ids.append(article_id)

    feed_ids = list_event_feed_ids(event_id)
    if not feed_ids:
        return ids

    try:
        rows = _fetch_rows(
            """
            select a.id
            from articles a
            inner join feeds f on f.url = a.feed
            inner join event_feeds ef on ef.feed_id = f.id
            where ef.event_id = %s
            order by a.id asc
            """,
            (int(event_id),),
        )
    except Exception:
        rows = []

    for row in rows:
        try:
            article_id = int(row.get("id"))
        except Exception:
            continue
        if article_id in seen:
            continue
        seen.add(article_id)
        ids.append(article_id)

    return ids


def list_event_ids_for_feed_url(feed_url):
    if not config.DATABASE_URL:
        return []

    key = _normalize_url(feed_url)
    if not key:
        return []

    try:
        rows = _fetch_rows(
            """
            select e.id
            from events e
            inner join event_feeds ef on ef.event_id = e.id
            inner join feeds f on f.id = ef.feed_id
            where lower(f.url) = lower(%s)
            order by e.id asc
            """,
            (key,),
        )
    except Exception:
        return []

    ids = []
    seen = set()
    for row in rows:
        try:
            event_id = int(row.get("id"))
        except Exception:
            continue
        if event_id in seen:
            continue
        seen.add(event_id)
        ids.append(event_id)
    return ids


def diagnose_event_setup():
    if not config.DATABASE_URL:
        return "DATABASE_URL is missing."

    try:
        row = db.fetch_one("select 1 as ok")
        if not row:
            return "Database request failed."
        return ""
    except Exception as e:
        return f"Database request failed: {e}"
