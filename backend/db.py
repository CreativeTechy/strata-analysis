"""Shared Postgres helpers for the backend."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# Every request/thread that needs a connection (FastAPI handlers, the analysis
# pipeline's worker pool) went through its own psycopg.connect() before this -
# a fresh TCP handshake and auth round-trip per query. A pool amortizes that:
# min_size keeps a few connections warm, max_size caps how many the database
# ever sees at once regardless of how many threads ask.
DB_POOL_MIN_SIZE = int(os.environ.get("DB_POOL_MIN_SIZE", "1") or 1)
DB_POOL_MAX_SIZE = int(os.environ.get("DB_POOL_MAX_SIZE", "10") or 10)

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def get_database_url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url:
        return url

    host = (os.environ.get("POSTGRES_HOST") or os.environ.get("DB_HOST") or "").strip()
    port = (os.environ.get("POSTGRES_PORT") or os.environ.get("DB_PORT") or "5432").strip()
    name = (os.environ.get("POSTGRES_DB") or os.environ.get("DB_NAME") or "").strip()
    user = (os.environ.get("POSTGRES_USER") or os.environ.get("DB_USER") or "").strip()
    password = (os.environ.get("POSTGRES_PASSWORD") or os.environ.get("DB_PASSWORD") or "").strip()

    if not host or not name or not user:
        return ""

    auth = f"{user}:{password}@" if password else f"{user}@"
    return f"postgresql://{auth}{host}:{port}/{name}"


def _get_pool() -> ConnectionPool:
    """The process-wide pool, created on first use rather than at import time
    (DATABASE_URL may not be resolvable yet - e.g. dotenv loading in
    config.py runs after this module is first imported)."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            conninfo = get_database_url()
            if not conninfo:
                raise RuntimeError("DATABASE_URL is missing.")
            _pool = ConnectionPool(
                conninfo,
                min_size=DB_POOL_MIN_SIZE,
                max_size=DB_POOL_MAX_SIZE,
                kwargs={"row_factory": dict_row},
                open=True,
            )
    return _pool


def connect():
    """A pooled connection, checked out on `with connect() as conn:` entry and
    returned to the pool (not closed) on exit - a drop-in replacement for the
    bare `psycopg.connect()` this used to be, which every caller here already
    only ever used as a context manager."""
    return _get_pool().connection()


@contextmanager
def transaction():
    with connect() as conn:
        with conn.cursor() as cur:
            yield cur


def fetch_all(query: str, params: tuple[Any, ...] | list[Any] | None = None):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            rows = cur.fetchall()
            return rows if rows else []


def fetch_one(query: str, params: tuple[Any, ...] | list[Any] | None = None):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            return cur.fetchone()


def execute(query: str, params: tuple[Any, ...] | list[Any] | None = None):
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            try:
                row = cur.fetchone()
            except Exception:
                row = None
            return row

