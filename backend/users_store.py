"""Postgres-backed user management: bootstrap admin, CRUD, password checks."""

from __future__ import annotations

import bcrypt

import config
import db

ROLES = ("viewer", "editor", "operator", "admin")
STATUSES = ("active", "disabled")

USER_SELECT = "id,username,email,role,status,last_login_at,created_at,updated_at"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def _normalize(row):
    if not row:
        return None
    return {
        "id": row.get("id"),
        "username": row.get("username"),
        "email": row.get("email"),
        "role": row.get("role"),
        "status": row.get("status"),
        "last_login_at": row.get("last_login_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def count_users() -> int:
    row = db.fetch_one("select count(*)::int as total from users")
    return int((row or {}).get("total") or 0)


def get_user_by_username(username: str):
    if not username:
        return None
    row = db.fetch_one(
        f"select {USER_SELECT},password_hash from users where lower(username) = lower(%s) limit 1",
        (username,),
    )
    return row


def get_user_by_login(identifier: str):
    """Look up a user by username OR email - login accepts either."""
    if not identifier:
        return None
    row = db.fetch_one(
        f"""
        select {USER_SELECT},password_hash from users
        where lower(username) = lower(%s) or lower(email) = lower(%s)
        limit 1
        """,
        (identifier, identifier),
    )
    return row


def get_user_by_id(user_id):
    row = db.fetch_one(f"select {USER_SELECT} from users where id = %s limit 1", (user_id,))
    return _normalize(row)


def list_users():
    rows = db.fetch_all(f"select {USER_SELECT} from users order by created_at asc")
    return [_normalize(row) for row in rows]


def create_user(username: str, email: str, password: str, role: str):
    if role not in ROLES:
        raise ValueError(f"Invalid role: {role}")
    password_hash = hash_password(password)
    row = db.fetch_one(
        f"""
        insert into users (username, email, password_hash, role, status)
        values (%s, %s, %s, %s, 'active')
        returning {USER_SELECT}
        """,
        (username.strip(), (email or "").strip() or None, password_hash, role),
    )
    return _normalize(row)


def update_user(user_id, role: str | None = None, status: str | None = None):
    fields, params = [], []
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"Invalid role: {role}")
        fields.append("role = %s")
        params.append(role)
    if status is not None:
        if status not in STATUSES:
            raise ValueError(f"Invalid status: {status}")
        fields.append("status = %s")
        params.append(status)
    if not fields:
        return get_user_by_id(user_id)

    fields.append("updated_at = now()")
    params.append(user_id)
    row = db.fetch_one(
        f"update users set {', '.join(fields)} where id = %s returning {USER_SELECT}",
        tuple(params),
    )
    return _normalize(row)


def record_login(user_id) -> None:
    db.execute("update users set last_login_at = now() where id = %s", (user_id,))


def bootstrap_admin() -> None:
    """Create the initial admin user on first startup, if none exist yet."""
    if not config.DATABASE_URL:
        return
    try:
        if count_users() > 0:
            return
        if not config.ADMIN_BOOTSTRAP_USERNAME or not config.ADMIN_BOOTSTRAP_PASSWORD:
            print(
                "No users exist yet and ADMIN_BOOTSTRAP_USERNAME/ADMIN_BOOTSTRAP_PASSWORD "
                "are not set - skipping admin bootstrap. Set them in backend/.env and restart."
            )
            return
        create_user(
            config.ADMIN_BOOTSTRAP_USERNAME,
            config.ADMIN_BOOTSTRAP_EMAIL,
            config.ADMIN_BOOTSTRAP_PASSWORD,
            "admin",
        )
        print(f"Bootstrapped initial admin user '{config.ADMIN_BOOTSTRAP_USERNAME}'.")
    except Exception as e:
        print(f"Admin bootstrap failed: {e}")
