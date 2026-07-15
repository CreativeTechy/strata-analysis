"""Cookie-session auth: cookie helpers, session validation, CSRF, FastAPI deps.

Session model: the cookie carries a random opaque token; only its hash lives
in the `sessions` table (see sessions_store.py), so a DB leak can't be used to
replay live sessions. CSRF uses the double-submit pattern: a second, readable
cookie holds a token tied to the session row; mutating requests must echo it
back in the `X-CSRF-Token` header.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Response

import config
import permissions_store
import sessions_store
import users_store

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def set_auth_cookies(response: Response, raw_token: str, csrf_token: str, expires_at: datetime) -> None:
    max_age = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        config.SESSION_COOKIE_NAME,
        raw_token,
        max_age=max_age,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        path="/",
    )
    # Not HttpOnly: the dashboard's fetch wrapper reads this to set the
    # X-CSRF-Token header on mutating requests (double-submit CSRF check).
    response.set_cookie(
        config.CSRF_COOKIE_NAME,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=config.COOKIE_SECURE,
        samesite=config.COOKIE_SAMESITE,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(config.SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(config.CSRF_COOKIE_NAME, path="/")


def get_current_user(request: Request) -> dict:
    """Resolve the session cookie into an active user, or raise 401."""
    raw_token = request.cookies.get(config.SESSION_COOKIE_NAME)
    session = sessions_store.get_session(raw_token) if raw_token else None
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    user = users_store.get_user_by_id(session["user_id"])
    if not user or user["status"] != "active":
        raise HTTPException(status_code=401, detail="Not authenticated.")

    sessions_store.touch_session(raw_token)
    request.state.session = session
    request.state.user = user
    return user


def _enforce_csrf(request: Request) -> None:
    if request.method not in UNSAFE_METHODS:
        return
    session = getattr(request.state, "session", None)
    header_token = request.headers.get("X-CSRF-Token", "")
    if not session or not header_token or not hmac.compare_digest(header_token, session["csrf_token"]):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token.")


def require_permission(*permissions: str):
    """Dependency factory: require an authenticated user who holds every
    permission in `permissions` (roles with full_access always pass), and
    CSRF-check mutating requests.

    Call with no permissions for "any authenticated user" endpoints.
    """
    required = set(permissions)

    def _check(request: Request, user: dict = Depends(get_current_user)) -> dict:
        if required and not required.issubset(permissions_store.user_permission_keys(user)):
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        _enforce_csrf(request)
        return user

    return _check


def require_any_permission(*permissions: str):
    """Like require_permission, but passes if the user holds at least one of
    `permissions` instead of all of them (e.g. an action usable from either a
    create or an edit flow)."""
    required = set(permissions)

    def _check(request: Request, user: dict = Depends(get_current_user)) -> dict:
        if required and not required & permissions_store.user_permission_keys(user):
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        _enforce_csrf(request)
        return user

    return _check
