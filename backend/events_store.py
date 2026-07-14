"""Postgres-backed event helpers."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Iterable
from urllib.parse import unquote, urlparse, urlunparse

import config
import db
from embeddings import build_event_embedding_text, get_embedding
from psycopg.types.json import Jsonb


EVENT_SELECT = (
    "id,name,status,description,location,target_audience,hashtags,keywords,usernames,"
    "start_date,end_date,embedding_json,embedding_model,embedding_source,embedded_at,"
    "repeat_enabled,repeat_interval_value,repeat_interval_unit,next_run_at,last_run_at,last_run_status,"
    "created_at,updated_at"
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
    "repeat_enabled",
    "repeat_interval_value",
    "repeat_interval_unit",
)
EVENT_EMBEDDING_FIELDS = ("embedding_json", "embedding_model", "embedding_source", "embedded_at")
EVENT_SCHEDULE_FIELDS = ("next_run_at", "last_run_at", "last_run_status")

REPEAT_INTERVAL_UNITS = ("minutes", "hours", "days")


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


def _event_schedule_fields():
    columns = _event_columns()
    return [field for field in EVENT_SCHEDULE_FIELDS if field in columns]


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


def _normalize_event(row, source_ids=None):
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
        "repeat_enabled": bool(row.get("repeat_enabled", False)),
        "repeat_interval_value": row.get("repeat_interval_value"),
        "repeat_interval_unit": (row.get("repeat_interval_unit") or "").strip().lower(),
        "next_run_at": row.get("next_run_at"),
        "last_run_at": row.get("last_run_at"),
        "last_run_status": (row.get("last_run_status") or "").strip(),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "source_ids": _clean_ids(source_ids or []),
    }


def _normalize_source(row):
    url = (row.get("url") or "").strip()
    name = (row.get("name") or "").strip() or url
    source_type = config._resolve_source_type(row.get("source_type") or "", url)
    return {
        "id": row.get("id"),
        "url": url,
        "name": name,
        "enabled": bool(row.get("enabled", True)),
        "source_type": source_type,
        "category": (row.get("category") or "").strip(),
        "limited": bool(row.get("limited", False)),
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


def _fetch_event_source_map():
    rows = _fetch_rows("select event_id, source_id from event_sources order by event_id asc, source_id asc")
    mapping = defaultdict(list)
    for row in rows:
        try:
            event_id = int(row.get("event_id"))
            source_id = int(row.get("source_id"))
        except Exception:
            continue
        mapping[event_id].append(source_id)
    return mapping


def _fetch_source_event_map():
    rows = _fetch_rows("select event_id, source_id from event_sources order by source_id asc, event_id asc")
    mapping = defaultdict(list)
    for row in rows:
        try:
            event_id = int(row.get("event_id"))
            source_id = int(row.get("source_id"))
        except Exception:
            continue
        mapping[source_id].append(event_id)
    return mapping


def _fetch_source_url_map():
    rows = _fetch_rows("select id, url from sources order by id asc")
    mapping = defaultdict(list)
    for row in rows:
        try:
            source_id = int(row.get("id"))
        except Exception:
            continue
        key = _normalize_url(row.get("url"))
        if key:
            mapping[key].append(source_id)
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
        source_map = _fetch_event_source_map()
        return [_normalize_event(row, source_map.get(row.get("id"), [])) for row in rows]
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
        source_map = _fetch_event_source_map()
        events = [_normalize_event(row, source_map.get(row.get("id"), [])) for row in rows if isinstance(row, dict)]
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
        source_map = _fetch_event_source_map()
        return _normalize_event(rows[0], source_map.get(rows[0].get("id"), []))
    except Exception:
        return None


def _validate_repeat_fields(repeat_enabled, interval_value, interval_unit):
    """Raise ValueError on bad input; return (value, unit) normalized for storage."""
    unit = str(interval_unit or "").strip().lower()

    if not repeat_enabled:
        # Preserve a previously configured interval so re-enabling keeps the old cadence,
        # but don't hard-fail on garbage input for a disabled schedule.
        try:
            value = int(interval_value) if interval_value not in (None, "") else None
        except Exception:
            value = None
        if value is not None and value <= 0:
            value = None
        if unit and unit not in REPEAT_INTERVAL_UNITS:
            unit = ""
        return value, unit

    try:
        value = int(interval_value)
    except Exception:
        raise ValueError("repeat_interval_value must be a positive integer when repeat is enabled.")
    if value <= 0:
        raise ValueError("repeat_interval_value must be greater than 0 when repeat is enabled.")
    if unit not in REPEAT_INTERVAL_UNITS:
        raise ValueError(f"repeat_interval_unit must be one of {', '.join(REPEAT_INTERVAL_UNITS)}.")
    return value, unit


def _compute_next_run_at(base_time, value, unit):
    if not value or unit not in REPEAT_INTERVAL_UNITS:
        return None

    if isinstance(base_time, str):
        try:
            base_time = datetime.fromisoformat(base_time.replace("Z", "+00:00"))
        except Exception:
            base_time = None
    if not isinstance(base_time, datetime):
        base_time = datetime.now(timezone.utc)
    if base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=timezone.utc)

    if unit == "minutes":
        delta = timedelta(minutes=value)
    elif unit == "hours":
        delta = timedelta(hours=value)
    else:
        delta = timedelta(days=value)
    return base_time + delta


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

    repeat_enabled = bool(event.get("repeat_enabled"))
    repeat_interval_value, repeat_interval_unit = _validate_repeat_fields(
        repeat_enabled, event.get("repeat_interval_value"), event.get("repeat_interval_unit")
    )

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
        "repeat_enabled": repeat_enabled,
        "repeat_interval_value": repeat_interval_value,
        "repeat_interval_unit": repeat_interval_unit or None,
    }


def _apply_repeat_schedule(event_id, previous, payload):
    """Recompute next_run_at when the repeat settings actually changed; system fields only."""
    if "next_run_at" not in _event_schedule_fields():
        return None

    repeat_enabled = payload["repeat_enabled"]
    interval_value = payload["repeat_interval_value"]
    interval_unit = payload["repeat_interval_unit"]
    previous = previous or {}

    if not repeat_enabled:
        if not previous.get("repeat_enabled") and previous.get("next_run_at") is None:
            return None
        next_run_at = None
    else:
        interval_changed = (
            not previous.get("repeat_enabled")
            or previous.get("repeat_interval_value") != interval_value
            or (previous.get("repeat_interval_unit") or None) != interval_unit
            or previous.get("next_run_at") is None
        )
        if not interval_changed:
            return None
        next_run_at = _compute_next_run_at(previous.get("last_run_at"), interval_value, interval_unit)

    try:
        row = db.fetch_one(
            f"""
            update events
            set next_run_at = %s
            where id = %s
            returning {_event_select_sql()}
            """,
            (next_run_at, int(event_id)),
        )
        return _normalize_event(row) if row else None
    except Exception:
        return None


def list_due_events():
    """Events with repeat enabled whose next_run_at has passed."""
    if not config.DATABASE_URL or "next_run_at" not in _event_schedule_fields():
        return []

    try:
        rows = db.fetch_all(
            f"""
            select {_event_select_sql()}
            from events
            where repeat_enabled = true
              and next_run_at is not null
              and next_run_at <= now()
            order by next_run_at asc
            """
        )
        source_map = _fetch_event_source_map()
        return [_normalize_event(row, source_map.get(row.get("id"), [])) for row in rows]
    except Exception:
        return []


def claim_due_event(event_id):
    """Atomically clear next_run_at so only one poller starts this event's run."""
    if not config.DATABASE_URL:
        return False

    try:
        row = db.fetch_one(
            """
            update events
            set next_run_at = null
            where id = %s
              and repeat_enabled = true
              and next_run_at is not null
              and next_run_at <= now()
            returning id
            """,
            (int(event_id),),
        )
        return bool(row)
    except Exception:
        return False


def record_run_completion(event_id, *, status, completed_at=None):
    """Stamp last_run_at/last_run_status and, if repeat is enabled, schedule the next run."""
    if not config.DATABASE_URL or event_id is None:
        return None

    completed_at = completed_at or datetime.now(timezone.utc)
    event = get_event(event_id)
    if not event:
        return None

    assignments = ["last_run_at = %s", "last_run_status = %s"]
    params = [completed_at, str(status or "").strip().lower()]

    if event.get("repeat_enabled") and event.get("repeat_interval_value") and event.get("repeat_interval_unit"):
        next_run_at = _compute_next_run_at(
            completed_at, event.get("repeat_interval_value"), event.get("repeat_interval_unit")
        )
        assignments.append("next_run_at = %s")
        params.append(next_run_at)

    params.append(int(event_id))
    try:
        row = db.fetch_one(
            f"""
            update events
            set {", ".join(assignments)}
            where id = %s
            returning {_event_select_sql()}
            """,
            params,
        )
        return _normalize_event(row) if row else None
    except Exception:
        return None


def _set_event_sources(event_id, source_ids):
    event_id = int(event_id)
    source_ids = _clean_ids(source_ids)
    try:
        db.execute("delete from event_sources where event_id = %s", (event_id,))
        for source_id in source_ids:
            db.execute(
                """
                insert into event_sources (event_id, source_id)
                values (%s, %s)
                on conflict (event_id, source_id) do nothing
                """,
                (event_id, source_id),
            )
        return source_ids
    except Exception:
        return []


def persist_event_embedding_for_id(event_id):
    if not config.DATABASE_URL:
        return {}

    event = get_event(event_id)
    if not event:
        return {}
    return _persist_event_embedding(event)


def create_event(event, *, embed=True):
    if not config.DATABASE_URL:
        return None

    payload = _event_payload(event)
    if not payload["name"]:
        return None

    source_ids = _clean_ids(event.get("source_ids") or [])
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
        if embed:
            created.update(_persist_event_embedding(created))
        if source_ids:
            created["source_ids"] = set_event_sources(created["id"], source_ids)
        else:
            created["source_ids"] = []
        schedule_update = _apply_repeat_schedule(created["id"], None, payload)
        if schedule_update:
            created["next_run_at"] = schedule_update.get("next_run_at")
        return created
    except Exception as e:
        raise RuntimeError(f"Database request failed: {e}") from e


def update_event(event_id, event, *, embed=True):
    if not config.DATABASE_URL:
        return None

    previous = get_event(event_id)
    payload = _event_payload(event)
    source_ids = event.get("source_ids") if isinstance(event, dict) else None
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
        if embed:
            normalized.update(_persist_event_embedding(normalized))
        if source_ids is not None:
            normalized["source_ids"] = _set_event_sources(event_id, source_ids)
        else:
            normalized["source_ids"] = list_event_source_ids(event_id)
        schedule_update = _apply_repeat_schedule(event_id, previous, payload)
        if schedule_update:
            normalized["next_run_at"] = schedule_update.get("next_run_at")
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


def list_event_source_ids(event_id):
    if not config.DATABASE_URL:
        return []

    try:
        rows = _fetch_rows(
            "select source_id from event_sources where event_id = %s order by source_id asc",
            (int(event_id),),
        )
        ids = []
        seen = set()
        for row in rows:
            try:
                source_id = int(row.get("source_id"))
            except Exception:
                continue
            if source_id not in seen:
                seen.add(source_id)
                ids.append(source_id)
        return ids
    except Exception:
        return []


def list_source_event_ids(source_id):
    if not config.DATABASE_URL:
        return []

    try:
        rows = _fetch_rows(
            "select event_id from event_sources where source_id = %s order by event_id asc",
            (int(source_id),),
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


def set_event_sources(event_id, source_ids):
    if not config.DATABASE_URL:
        return []
    return _set_event_sources(event_id, source_ids)


def set_source_events(source_id, event_ids):
    if not config.DATABASE_URL:
        return []

    source_id = int(source_id)
    event_ids = _clean_ids(event_ids)
    try:
        db.execute("delete from event_sources where source_id = %s", (source_id,))
        for event_id in event_ids:
            db.execute(
                """
                insert into event_sources (event_id, source_id)
                values (%s, %s)
                on conflict (event_id, source_id) do nothing
                """,
                (event_id, source_id),
            )
        return event_ids
    except Exception:
        return []


def list_sources_for_event(event_id):
    if not config.DATABASE_URL:
        return []

    try:
        rows = _fetch_rows(
            """
            select f.id, f.url, f.name, f.enabled, f.source_type, f.category, f.limited, f.created_at, f.updated_at
            from sources f
            inner join event_sources ef on ef.source_id = f.id
            where ef.event_id = %s
            order by f.created_at asc
            """,
            (int(event_id),),
        )
        return [_normalize_source(row) for row in rows]
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

    source_ids = list_event_source_ids(event_id)
    if not source_ids:
        return ids

    try:
        rows = _fetch_rows(
            """
            select a.id
            from articles a
            inner join sources f on f.url = a.source_url
            inner join event_sources ef on ef.source_id = f.id
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


def list_event_ids_for_source_url(source_url):
    if not config.DATABASE_URL:
        return []

    key = _normalize_url(source_url)
    if not key:
        return []

    try:
        rows = _fetch_rows(
            """
            select e.id
            from events e
            inner join event_sources ef on ef.event_id = e.id
            inner join sources f on f.id = ef.source_id
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
