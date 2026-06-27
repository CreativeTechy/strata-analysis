"""Pipeline run tracking helpers for Supabase-backed observability."""

import uuid

import requests

import config


def _headers():
    return {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _endpoint():
    return f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/pipeline_runs"


def _normalize(row):
    return {
        "id": row.get("id"),
        "pipeline": row.get("pipeline") or "scrape",
        "event_id": row.get("event_id"),
        "status": row.get("status") or "queued",
        "stage": row.get("stage") or "queued",
        "message": row.get("message") or "",
        "articles_scraped": row.get("articles_scraped") or 0,
        "articles_cleaned": row.get("articles_cleaned") or 0,
        "articles_saved": row.get("articles_saved") or 0,
        "crawl_pages": row.get("crawl_pages") or 0,
        "error": row.get("error") or "",
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _fetch_by_id(run_id):
    resp = requests.get(
        _endpoint(),
        headers=_headers(),
        params={
            "select": "id,pipeline,event_id,status,stage,message,articles_scraped,articles_cleaned,articles_saved,crawl_pages,error,started_at,finished_at,created_at,updated_at",
            "id": f"eq.{run_id}",
            "limit": 1,
        },
        timeout=15,
    )
    resp.raise_for_status()
    rows = resp.json()
    if isinstance(rows, list) and rows:
        return _normalize(rows[0])
    return None


def list_pipeline_runs(limit=10):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []

    try:
        resp = requests.get(
            _endpoint(),
            headers=_headers(),
            params={
                "select": "id,pipeline,event_id,status,stage,message,articles_scraped,articles_cleaned,articles_saved,crawl_pages,error,started_at,finished_at,created_at,updated_at",
                "order": "created_at.desc",
                "limit": str(limit),
            },
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json()
        if isinstance(rows, list):
            return [_normalize(row) for row in rows]
    except Exception:
        return []
    return []


def create_pipeline_run(run_id=None, pipeline="scrape", event_id=None, status="queued", stage="queued", message=""):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return None

    run_id = run_id or uuid.uuid4().hex
    payload = {
        "id": run_id,
        "pipeline": pipeline,
        "event_id": event_id,
        "status": status,
        "stage": stage,
        "message": message,
    }

    try:
        resp = requests.post(
            _endpoint(),
            headers={**_headers(), "Prefer": "return=representation"},
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json() if resp.content else None
        if isinstance(rows, list) and rows:
            return _normalize(rows[0])
        if isinstance(rows, dict) and rows:
            return _normalize(rows)
        return _fetch_by_id(run_id)
    except Exception:
        return None


def update_pipeline_run(run_id, **fields):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY or not run_id:
        return None

    try:
        resp = requests.patch(
            _endpoint(),
            headers={**_headers(), "Prefer": "return=representation"},
            params={"id": f"eq.{run_id}"},
            json=fields,
            timeout=15,
        )
        resp.raise_for_status()
        rows = resp.json() if resp.content else None
        if isinstance(rows, list) and rows:
            return _normalize(rows[0])
        if isinstance(rows, dict) and rows:
            return _normalize(rows)
        return _fetch_by_id(run_id)
    except Exception:
        return None
