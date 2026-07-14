"""Postgres-backed session storage for cookie auth.

The cookie carries an opaque random token; only its SHA-256 hash is ever
persisted, so a database leak doesn't hand out live sessions.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import config
import db

SESSION_SELECT = "token_hash,user_id,csrf_token,created_at,last_seen_at,expires_at"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id) -> tuple[str, str, datetime]:
    """Create a session row and return (raw_token, csrf_token, expires_at)."""
    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=config.SESSION_TTL_HOURS)

    db.execute(
        """
        insert into sessions (token_hash, user_id, csrf_token, expires_at)
        values (%s, %s, %s, %s)
        """,
        (_hash_token(raw_token), user_id, csrf_token, expires_at),
    )
    return raw_token, csrf_token, expires_at


def get_session(raw_token: str):
    if not raw_token:
        return None
    row = db.fetch_one(
        f"select {SESSION_SELECT} from sessions where token_hash = %s limit 1",
        (_hash_token(raw_token),),
    )
    if not row:
        return None
    expires_at = row.get("expires_at")
    if expires_at is not None and expires_at < datetime.now(timezone.utc):
        return None
    return row


def touch_session(raw_token: str) -> None:
    db.execute(
        "update sessions set last_seen_at = now() where token_hash = %s",
        (_hash_token(raw_token),),
    )


def delete_session(raw_token: str) -> None:
    if not raw_token:
        return
    db.execute("delete from sessions where token_hash = %s", (_hash_token(raw_token),))


def delete_sessions_for_user(user_id) -> None:
    db.execute("delete from sessions where user_id = %s", (user_id,))
