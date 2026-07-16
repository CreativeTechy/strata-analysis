"""Postgres-backed project helpers."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Iterable
from urllib.parse import unquote, urlparse, urlunparse

import config
import db
import users_store
from embeddings import build_project_embedding_text, get_embedding
from psycopg.types.json import Jsonb


PROJECT_SELECT = (
    "id,name,status,description,location,location_type,target_audience,hashtags,keywords,usernames,"
    "start_date,end_date,embedding_json,embedding_model,embedding_source,embedded_at,"
    "repeat_enabled,repeat_interval_value,repeat_interval_unit,first_run_at,repeat_weekdays,"
    "next_run_at,last_run_at,last_run_status,"
    "created_at,updated_at"
)

PROJECT_SELECT_FIELDS = tuple(PROJECT_SELECT.split(","))
PROJECT_MUTABLE_FIELDS = (
    "name",
    "status",
    "description",
    "location",
    "location_type",
    "target_audience",
    "hashtags",
    "keywords",
    "usernames",
    "start_date",
    "end_date",
    "repeat_enabled",
    "repeat_interval_value",
    "repeat_interval_unit",
    "first_run_at",
    "repeat_weekdays",
)
PROJECT_EMBEDDING_FIELDS = ("embedding_json", "embedding_model", "embedding_source", "embedded_at")
PROJECT_SCHEDULE_FIELDS = ("next_run_at", "last_run_at", "last_run_status")

REPEAT_INTERVAL_UNITS = ("minutes", "hours", "days")
LOCATION_TYPES = ("on_site", "remote", "hybrid")
REPEAT_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WEEKDAY_INDEX = {day: index for index, day in enumerate(REPEAT_WEEKDAYS)}


@lru_cache(maxsize=1)
def _project_table_columns():
    if not config.DATABASE_URL:
        return set()

    try:
        rows = db.fetch_all(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'projects'
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


def _project_columns():
    columns = _project_table_columns()
    if columns:
        return columns
    return set(PROJECT_SELECT_FIELDS)


def _project_select_sql():
    columns = _project_columns()
    selected = [field for field in PROJECT_SELECT_FIELDS if field in columns]
    return ",".join(selected or ["id", "name", "status", "start_date", "end_date", "created_at", "updated_at"])


def _project_write_fields():
    columns = _project_columns()
    return [field for field in PROJECT_MUTABLE_FIELDS if field in columns]


def _project_embedding_fields():
    columns = _project_columns()
    return [field for field in PROJECT_EMBEDDING_FIELDS if field in columns]


def _project_schedule_fields():
    columns = _project_columns()
    return [field for field in PROJECT_SCHEDULE_FIELDS if field in columns]


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


def _normalize_project(row, source_ids=None, user_ids=None):
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
        "location_type": (row.get("location_type") or "").strip().lower(),
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
        "first_run_at": row.get("first_run_at"),
        "repeat_weekdays": _validate_weekdays(row.get("repeat_weekdays")),
        "next_run_at": row.get("next_run_at"),
        "last_run_at": row.get("last_run_at"),
        "last_run_status": (row.get("last_run_status") or "").strip(),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "source_ids": _clean_ids(source_ids or []),
        "user_ids": _clean_ids(user_ids or []),
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


def _fetch_project_source_map():
    rows = _fetch_rows("select project_id, source_id from project_sources order by project_id asc, source_id asc")
    mapping = defaultdict(list)
    for row in rows:
        try:
            project_id = int(row.get("project_id"))
            source_id = int(row.get("source_id"))
        except Exception:
            continue
        mapping[project_id].append(source_id)
    return mapping


def _fetch_project_user_map():
    rows = _fetch_rows("select project_id, user_id from project_users order by project_id asc, user_id asc")
    mapping = defaultdict(list)
    for row in rows:
        try:
            project_id = int(row.get("project_id"))
            user_id = int(row.get("user_id"))
        except Exception:
            continue
        mapping[project_id].append(user_id)
    return mapping


def _fetch_user_project_map():
    rows = _fetch_rows("select project_id, user_id from project_users order by user_id asc, project_id asc")
    mapping = defaultdict(list)
    for row in rows:
        try:
            project_id = int(row.get("project_id"))
            user_id = int(row.get("user_id"))
        except Exception:
            continue
        mapping[user_id].append(project_id)
    return mapping


def _fetch_source_project_map():
    rows = _fetch_rows("select project_id, source_id from project_sources order by source_id asc, project_id asc")
    mapping = defaultdict(list)
    for row in rows:
        try:
            project_id = int(row.get("project_id"))
            source_id = int(row.get("source_id"))
        except Exception:
            continue
        mapping[source_id].append(project_id)
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


def _fetch_article_project_map(project_id):
    rows = _fetch_rows(
        "select article_id from article_projects where project_id = %s order by article_id asc",
        (int(project_id),),
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


def _persist_project_embedding(project):
    if not config.DATABASE_URL:
        return {}

    embedding_fields = _project_embedding_fields()
    if not embedding_fields:
        return {}

    text = build_project_embedding_text(project)
    if not text:
        return {}

    embedding = get_embedding(text)
    if not embedding:
        return {}

    try:
        project_id = int(project.get("id"))
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
        params.append(project_id)
        row = db.fetch_one(
            f"""
            update projects
            set {", ".join(assignments)}
            where id = %s
            returning {_project_select_sql()}
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


def list_projects(visible_project_ids=None):
    """`visible_project_ids=None` returns every project (admin/full_access
    view); otherwise only the given ids are returned, e.g. to scope non-admin
    users to the projects they're linked to via project_users."""
    if not config.DATABASE_URL:
        return []

    try:
        where_sql = ""
        params = ()
        if visible_project_ids is not None:
            ids = _clean_ids(visible_project_ids)
            if not ids:
                return []
            where_sql = "where id = any(%s)"
            params = (ids,)
        rows = db.fetch_all(
            f"""
            select {_project_select_sql()}
            from projects
            {where_sql}
            order by created_at asc
            """,
            params,
        )
        source_map = _fetch_project_source_map()
        user_map = _fetch_project_user_map()
        return [
            _normalize_project(row, source_map.get(row.get("id"), []), user_map.get(row.get("id"), []))
            for row in rows
        ]
    except Exception:
        return []


def list_projects_page(limit=25, offset=0, visible_project_ids=None):
    if not config.DATABASE_URL:
        return {"projects": [], "total": 0, "limit": int(limit or 0), "offset": int(offset or 0)}

    limit = max(1, min(int(limit or 25), 100))
    offset = max(0, int(offset or 0))

    try:
        where_sql = ""
        count_where_sql = ""
        list_params = []
        count_params = []
        if visible_project_ids is not None:
            ids = _clean_ids(visible_project_ids)
            if not ids:
                return {"projects": [], "total": 0, "limit": limit, "offset": offset}
            where_sql = "where id = any(%s)"
            count_where_sql = "where id = any(%s)"
            list_params = [ids]
            count_params = [ids]

        rows = db.fetch_all(
            f"""
            select {_project_select_sql()}
            from projects
            {where_sql}
            order by created_at asc
            limit %s offset %s
            """,
            (*list_params, limit, offset),
        )
        total_row = db.fetch_one(
            f"select count(*)::int as total from projects {count_where_sql}", tuple(count_params)
        )
        source_map = _fetch_project_source_map()
        user_map = _fetch_project_user_map()
        projects = [
            _normalize_project(row, source_map.get(row.get("id"), []), user_map.get(row.get("id"), []))
            for row in rows
            if isinstance(row, dict)
        ]
        total = int((total_row or {}).get("total") or len(projects))
        return {"projects": projects, "total": total, "limit": limit, "offset": offset}
    except Exception:
        return {"projects": [], "total": 0, "limit": limit, "offset": offset}


def get_project(project_id):
    if not config.DATABASE_URL:
        return None

    try:
        rows = db.fetch_all(
            f"""
            select {_project_select_sql()}
            from projects
            where id = %s
            limit 1
            """,
            (int(project_id),),
        )
        if not rows:
            return None
        source_map = _fetch_project_source_map()
        user_map = _fetch_project_user_map()
        return _normalize_project(rows[0], source_map.get(rows[0].get("id"), []), user_map.get(rows[0].get("id"), []))
    except Exception:
        return None


def _validate_location_type(value):
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text not in LOCATION_TYPES:
        raise ValueError(f"location_type must be one of {', '.join(LOCATION_TYPES)}.")
    return text


def _validate_weekdays(values):
    cleaned = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip().lower()
        if text and text in WEEKDAY_INDEX and text not in seen:
            seen.add(text)
            cleaned.append(text)
    return cleaned


def _coerce_datetime(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except Exception:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _apply_weekday_filter(base_time, weekdays):
    """Roll `base_time` forward (never backward) to the next day matching one of `weekdays`."""
    if not isinstance(base_time, datetime):
        return base_time
    allowed = {WEEKDAY_INDEX[day] for day in weekdays or [] if day in WEEKDAY_INDEX}
    if not allowed:
        return base_time
    candidate = base_time
    for _ in range(7):
        if candidate.weekday() in allowed:
            return candidate
        candidate = candidate + timedelta(days=1)
    return base_time


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


def _compute_next_run_at(base_time, value, unit, weekdays=None):
    if not value or unit not in REPEAT_INTERVAL_UNITS:
        return None

    base_time = _coerce_datetime(base_time) or datetime.now(timezone.utc)

    if unit == "minutes":
        delta = timedelta(minutes=value)
    elif unit == "hours":
        delta = timedelta(hours=value)
    else:
        delta = timedelta(days=value)
    return _apply_weekday_filter(base_time + delta, weekdays)


def _project_payload(project):
    if not isinstance(project, dict):
        project = {}

    hashtags = project.get("hashtags")
    keywords = project.get("keywords")
    usernames = project.get("usernames")
    if isinstance(hashtags, str):
        hashtags = [part.strip() for part in hashtags.replace("\n", ",").split(",")]
    if isinstance(keywords, str):
        keywords = [part.strip() for part in keywords.replace("\n", ",").split(",")]
    if isinstance(usernames, str):
        usernames = [part.strip() for part in usernames.replace("\n", ",").split(",")]

    repeat_enabled = bool(project.get("repeat_enabled"))
    repeat_interval_value, repeat_interval_unit = _validate_repeat_fields(
        repeat_enabled, project.get("repeat_interval_value"), project.get("repeat_interval_unit")
    )

    return {
        "name": (project.get("name") or "").strip(),
        "status": (project.get("status") or "draft").strip().lower() or "draft",
        "description": (project.get("description") or "").strip() or None,
        "location": (project.get("location") or "").strip() or None,
        "location_type": _validate_location_type(project.get("location_type")),
        "target_audience": (project.get("target_audience") or "").strip() or None,
        "hashtags": _clean_terms(hashtags or []),
        "keywords": _clean_terms(keywords or []),
        "usernames": _clean_terms(usernames or []),
        "start_date": project.get("start_date") or None,
        "end_date": project.get("end_date") or None,
        "repeat_enabled": repeat_enabled,
        "repeat_interval_value": repeat_interval_value,
        "repeat_interval_unit": repeat_interval_unit or None,
        "first_run_at": _coerce_datetime(project.get("first_run_at")),
        "repeat_weekdays": _validate_weekdays(project.get("repeat_weekdays")),
    }


def _apply_repeat_schedule(project_id, previous, payload):
    """Recompute next_run_at when the repeat settings actually changed; system fields only."""
    if "next_run_at" not in _project_schedule_fields():
        return None

    repeat_enabled = payload["repeat_enabled"]
    interval_value = payload["repeat_interval_value"]
    interval_unit = payload["repeat_interval_unit"]
    first_run_at = payload.get("first_run_at")
    weekdays = payload.get("repeat_weekdays") or []
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
            or _coerce_datetime(previous.get("first_run_at")) != first_run_at
        )
        if not interval_changed:
            return None
        if first_run_at:
            # First (re)save of a repeating project: seed the schedule from the
            # user-chosen first run instead of "now + interval".
            next_run_at = _apply_weekday_filter(first_run_at, weekdays)
        else:
            next_run_at = _compute_next_run_at(previous.get("last_run_at"), interval_value, interval_unit, weekdays)

    try:
        row = db.fetch_one(
            f"""
            update projects
            set next_run_at = %s
            where id = %s
            returning {_project_select_sql()}
            """,
            (next_run_at, int(project_id)),
        )
        return _normalize_project(row) if row else None
    except Exception:
        return None


def list_due_projects():
    """Projects with repeat enabled whose next_run_at has passed."""
    if not config.DATABASE_URL or "next_run_at" not in _project_schedule_fields():
        return []

    try:
        rows = db.fetch_all(
            f"""
            select {_project_select_sql()}
            from projects
            where repeat_enabled = true
              and next_run_at is not null
              and next_run_at <= now()
            order by next_run_at asc
            """
        )
        source_map = _fetch_project_source_map()
        user_map = _fetch_project_user_map()
        return [
            _normalize_project(row, source_map.get(row.get("id"), []), user_map.get(row.get("id"), []))
            for row in rows
        ]
    except Exception:
        return []


def claim_due_project(project_id):
    """Atomically clear next_run_at so only one poller starts this project's run."""
    if not config.DATABASE_URL:
        return False

    try:
        row = db.fetch_one(
            """
            update projects
            set next_run_at = null
            where id = %s
              and repeat_enabled = true
              and next_run_at is not null
              and next_run_at <= now()
            returning id
            """,
            (int(project_id),),
        )
        return bool(row)
    except Exception:
        return False


def record_run_completion(project_id, *, status, completed_at=None):
    """Stamp last_run_at/last_run_status and, if repeat is enabled, schedule the next run."""
    if not config.DATABASE_URL or project_id is None:
        return None

    completed_at = completed_at or datetime.now(timezone.utc)
    project = get_project(project_id)
    if not project:
        return None

    assignments = ["last_run_at = %s", "last_run_status = %s"]
    params = [completed_at, str(status or "").strip().lower()]

    if project.get("repeat_enabled") and project.get("repeat_interval_value") and project.get("repeat_interval_unit"):
        next_run_at = _compute_next_run_at(
            completed_at,
            project.get("repeat_interval_value"),
            project.get("repeat_interval_unit"),
            project.get("repeat_weekdays"),
        )
        assignments.append("next_run_at = %s")
        params.append(next_run_at)

    params.append(int(project_id))
    try:
        row = db.fetch_one(
            f"""
            update projects
            set {", ".join(assignments)}
            where id = %s
            returning {_project_select_sql()}
            """,
            params,
        )
        return _normalize_project(row) if row else None
    except Exception:
        return None


def _set_project_sources(project_id, source_ids):
    project_id = int(project_id)
    source_ids = _clean_ids(source_ids)
    try:
        db.execute("delete from project_sources where project_id = %s", (project_id,))
        for source_id in source_ids:
            db.execute(
                """
                insert into project_sources (project_id, source_id)
                values (%s, %s)
                on conflict (project_id, source_id) do nothing
                """,
                (project_id, source_id),
            )
        return source_ids
    except Exception:
        return []


def _set_project_users(project_id, user_ids):
    project_id = int(project_id)
    user_ids = _clean_ids(user_ids)
    try:
        db.execute("delete from project_users where project_id = %s", (project_id,))
        for user_id in user_ids:
            db.execute(
                """
                insert into project_users (project_id, user_id)
                values (%s, %s)
                on conflict (project_id, user_id) do nothing
                """,
                (project_id, user_id),
            )
        return user_ids
    except Exception:
        return []


def persist_project_embedding_for_id(project_id):
    if not config.DATABASE_URL:
        return {}

    project = get_project(project_id)
    if not project:
        return {}
    return _persist_project_embedding(project)


def create_project(project, *, embed=True):
    if not config.DATABASE_URL:
        return None

    payload = _project_payload(project)
    if not payload["name"]:
        return None

    source_ids = _clean_ids(project.get("source_ids") or [])
    # Every project is linked to the admin (full_access) user(s) by default,
    # on top of whatever users were explicitly selected at creation time.
    user_ids = _clean_ids(list(project.get("user_ids") or []) + users_store.list_full_access_user_ids())
    try:
        write_fields = _project_write_fields()
        if not write_fields:
            return None
        insert_columns = ", ".join(write_fields)
        insert_values = ", ".join(["%s"] * len(write_fields))
        params = [
            _jsonb_param(payload[field]) if field in {"hashtags", "keywords", "usernames", "repeat_weekdays"} else payload[field]
            for field in write_fields
        ]
        row = db.fetch_one(
            f"""
            insert into projects ({insert_columns})
            values ({insert_values})
            returning {_project_select_sql()}
            """,
            params,
        )
        if not row:
            return None
        created = _normalize_project(row)
        if embed:
            created.update(_persist_project_embedding(created))
        if source_ids:
            created["source_ids"] = set_project_sources(created["id"], source_ids)
        else:
            created["source_ids"] = []
        if user_ids:
            created["user_ids"] = set_project_users(created["id"], user_ids)
        else:
            created["user_ids"] = []
        schedule_update = _apply_repeat_schedule(created["id"], None, payload)
        if schedule_update:
            created["next_run_at"] = schedule_update.get("next_run_at")
        return created
    except Exception as e:
        raise RuntimeError(f"Database request failed: {e}") from e


def update_project(project_id, project, *, embed=True):
    if not config.DATABASE_URL:
        return None

    previous = get_project(project_id)
    payload = _project_payload(project)
    source_ids = project.get("source_ids") if isinstance(project, dict) else None
    user_ids = project.get("user_ids") if isinstance(project, dict) else None
    try:
        write_fields = _project_write_fields()
        if not write_fields:
            return None
        assignments = ", ".join(f"{field} = %s" for field in write_fields)
        params = [
            _jsonb_param(payload[field]) if field in {"hashtags", "keywords", "usernames", "repeat_weekdays"} else payload[field]
            for field in write_fields
        ]
        params.append(int(project_id))
        row = db.fetch_one(
            f"""
            update projects
            set {assignments},
                updated_at = now()
            where id = %s
            returning {_project_select_sql()}
            """,
            params,
        )
        if not row:
            return None
        normalized = _normalize_project(row)
        if embed:
            normalized.update(_persist_project_embedding(normalized))
        if source_ids is not None:
            normalized["source_ids"] = _set_project_sources(project_id, source_ids)
        else:
            normalized["source_ids"] = list_project_source_ids(project_id)
        if user_ids is not None:
            # Keep admin (full_access) users linked even if they weren't in
            # the submitted selection, so the "admin sees every project"
            # invariant survives edits to the linkage.
            merged_user_ids = _clean_ids(list(user_ids or []) + users_store.list_full_access_user_ids())
            normalized["user_ids"] = _set_project_users(project_id, merged_user_ids)
        else:
            normalized["user_ids"] = list_project_user_ids(project_id)
        schedule_update = _apply_repeat_schedule(project_id, previous, payload)
        if schedule_update:
            normalized["next_run_at"] = schedule_update.get("next_run_at")
        return normalized
    except Exception as e:
        raise RuntimeError(f"Database request failed: {e}") from e


def delete_project(project_id):
    if not config.DATABASE_URL:
        return False

    try:
        db.execute("delete from projects where id = %s", (int(project_id),))
        return True
    except Exception:
        return False


def list_project_source_ids(project_id):
    if not config.DATABASE_URL:
        return []

    try:
        rows = _fetch_rows(
            "select source_id from project_sources where project_id = %s order by source_id asc",
            (int(project_id),),
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


def list_source_project_ids(source_id):
    if not config.DATABASE_URL:
        return []

    try:
        rows = _fetch_rows(
            "select project_id from project_sources where source_id = %s order by project_id asc",
            (int(source_id),),
        )
        ids = []
        seen = set()
        for row in rows:
            try:
                project_id = int(row.get("project_id"))
            except Exception:
                continue
            if project_id not in seen:
                seen.add(project_id)
                ids.append(project_id)
        return ids
    except Exception:
        return []


def set_project_sources(project_id, source_ids):
    if not config.DATABASE_URL:
        return []
    return _set_project_sources(project_id, source_ids)


def set_project_users(project_id, user_ids):
    if not config.DATABASE_URL:
        return []
    return _set_project_users(project_id, user_ids)


def list_project_user_ids(project_id):
    if not config.DATABASE_URL:
        return []

    try:
        rows = _fetch_rows(
            "select user_id from project_users where project_id = %s order by user_id asc",
            (int(project_id),),
        )
        ids = []
        seen = set()
        for row in rows:
            try:
                user_id = int(row.get("user_id"))
            except Exception:
                continue
            if user_id not in seen:
                seen.add(user_id)
                ids.append(user_id)
        return ids
    except Exception:
        return []


def project_ids_by_user_map():
    """Bulk project_id lookup for every linked user, e.g. for the linkage UI roster."""
    if not config.DATABASE_URL:
        return {}
    return dict(_fetch_user_project_map())


def list_project_ids_for_user(user_id):
    """Project ids a non-admin user is linked to, i.e. the projects visible to them."""
    if not config.DATABASE_URL:
        return []

    try:
        rows = _fetch_rows(
            "select project_id from project_users where user_id = %s order by project_id asc",
            (int(user_id),),
        )
        ids = []
        seen = set()
        for row in rows:
            try:
                project_id = int(row.get("project_id"))
            except Exception:
                continue
            if project_id not in seen:
                seen.add(project_id)
                ids.append(project_id)
        return ids
    except Exception:
        return []


def set_source_projects(source_id, project_ids):
    if not config.DATABASE_URL:
        return []

    source_id = int(source_id)
    project_ids = _clean_ids(project_ids)
    try:
        db.execute("delete from project_sources where source_id = %s", (source_id,))
        for project_id in project_ids:
            db.execute(
                """
                insert into project_sources (project_id, source_id)
                values (%s, %s)
                on conflict (project_id, source_id) do nothing
                """,
                (project_id, source_id),
            )
        return project_ids
    except Exception:
        return []


def list_sources_for_project(project_id):
    if not config.DATABASE_URL:
        return []

    try:
        rows = _fetch_rows(
            """
            select f.id, f.url, f.name, f.enabled, f.source_type, f.limited, f.created_at, f.updated_at
            from sources f
            inner join project_sources ef on ef.source_id = f.id
            where ef.project_id = %s
            order by f.created_at asc
            """,
            (int(project_id),),
        )
        return [_normalize_source(row) for row in rows]
    except Exception:
        return []


def set_article_projects(article_ids, project_id, similarity_scores=None):
    if not config.DATABASE_URL:
        return 0

    article_ids = _clean_ids(article_ids)
    if not article_ids:
        return 0

    project_id = int(project_id)
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
        db.execute("delete from article_projects where project_id = %s and article_id = any(%s)", (project_id, article_ids))
        for article_id in article_ids:
            db.execute(
                """
                insert into article_projects (article_id, project_id, similarity_score)
                values (%s, %s, %s)
                on conflict (article_id, project_id) do update
                set similarity_score = excluded.similarity_score,
                    created_at = article_projects.created_at
                """,
                (article_id, project_id, score_map.get(article_id)),
            )
        return len(article_ids)
    except Exception:
        return 0


def list_article_similarity_scores_for_project(project_id):
    if not config.DATABASE_URL:
        return {}

    try:
        rows = _fetch_rows(
            "select article_id, similarity_score from article_projects where project_id = %s order by article_id asc",
            (int(project_id),),
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


def list_article_ids_for_project(project_id):
    if not config.DATABASE_URL:
        return []

    ids = []
    seen = set()

    for article_id in _fetch_article_project_map(project_id):
        if article_id in seen:
            continue
        seen.add(article_id)
        ids.append(article_id)

    source_ids = list_project_source_ids(project_id)
    if not source_ids:
        return ids

    try:
        rows = _fetch_rows(
            """
            select a.id
            from articles a
            inner join sources f on f.url = a.source_url
            inner join project_sources ef on ef.source_id = f.id
            where ef.project_id = %s
            order by a.id asc
            """,
            (int(project_id),),
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


def list_project_ids_for_source_url(source_url):
    if not config.DATABASE_URL:
        return []

    key = _normalize_url(source_url)
    if not key:
        return []

    try:
        rows = _fetch_rows(
            """
            select e.id
            from projects e
            inner join project_sources ef on ef.project_id = e.id
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
            project_id = int(row.get("id"))
        except Exception:
            continue
        if project_id in seen:
            continue
        seen.add(project_id)
        ids.append(project_id)
    return ids


def diagnose_project_setup():
    if not config.DATABASE_URL:
        return "DATABASE_URL is missing."

    try:
        row = db.fetch_one("select 1 as ok")
        if not row:
            return "Database request failed."
        return ""
    except Exception as e:
        return f"Database request failed: {e}"
