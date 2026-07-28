"""Postgres-backed user management: bootstrap admin, CRUD, password checks."""

from __future__ import annotations

import bcrypt

import config
import db
from services.auth import permissions_store

STATUSES = ("active", "disabled")

USER_SELECT = "u.id, u.username, u.email, u.role_id, r.name as role, u.status, u.last_login_at, u.created_at, u.updated_at"
USER_FROM = "from users u left join roles r on r.id = u.role_id"


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
        "role_id": row.get("role_id"),
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
        f"select {USER_SELECT}, u.password_hash {USER_FROM} where lower(u.username) = lower(%s) limit 1",
        (username,),
    )
    return row


def get_user_by_login(identifier: str):
    """Look up a user by username OR email - login accepts either."""
    if not identifier:
        return None
    row = db.fetch_one(
        f"""
        select {USER_SELECT}, u.password_hash {USER_FROM}
        where lower(u.username) = lower(%s) or lower(u.email) = lower(%s)
        limit 1
        """,
        (identifier, identifier),
    )
    return row


def get_user_by_id(user_id):
    row = db.fetch_one(f"select {USER_SELECT} {USER_FROM} where u.id = %s limit 1", (user_id,))
    return _normalize(row)


def list_users():
    rows = db.fetch_all(f"select {USER_SELECT} {USER_FROM} order by u.created_at asc")
    return [_normalize(row) for row in rows]


def list_full_access_user_ids() -> list[int]:
    """Ids of every user whose role is full_access (this app's "admin"), so
    project creation can auto-link them regardless of the role's name."""
    rows = db.fetch_all(
        """
        select u.id
        from users u
        join roles r on r.id = u.role_id
        where r.full_access = true
        """
    )
    ids = []
    for row in rows or []:
        try:
            ids.append(int(row.get("id")))
        except Exception:
            continue
    return ids


def create_user(username: str, email: str, password: str, role_id: int):
    password_hash = hash_password(password)
    row = db.fetch_one(
        """
        insert into users (username, email, password_hash, role_id, status)
        values (%s, %s, %s, %s, 'active')
        returning id
        """,
        (username.strip(), (email or "").strip() or None, password_hash, role_id),
    )
    return get_user_by_id(row["id"]) if row else None


def update_user(user_id, role_id: int | None = None, status: str | None = None):
    fields, params = [], []
    if role_id is not None:
        fields.append("role_id = %s")
        params.append(role_id)
    if status is not None:
        if status not in STATUSES:
            raise ValueError(f"Invalid status: {status}")
        fields.append("status = %s")
        params.append(status)
    if not fields:
        return get_user_by_id(user_id)

    fields.append("updated_at = now()")
    params.append(user_id)
    db.execute(f"update users set {', '.join(fields)} where id = %s", tuple(params))
    return get_user_by_id(user_id)


def delete_user(user_id) -> bool:
    if not get_user_by_id(user_id):
        return False
    db.execute("delete from users where id = %s", (user_id,))
    return True


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
        admin_role = permissions_store.get_role_by_name("admin")
        if not admin_role:
            print("No 'admin' role found - run schema.sql to seed default roles before bootstrapping.")
            return
        create_user(
            config.ADMIN_BOOTSTRAP_USERNAME,
            config.ADMIN_BOOTSTRAP_EMAIL,
            config.ADMIN_BOOTSTRAP_PASSWORD,
            admin_role["id"],
        )
        print(f"Bootstrapped initial admin user '{config.ADMIN_BOOTSTRAP_USERNAME}'.")
    except Exception as e:
        print(f"Admin bootstrap failed: {e}")
