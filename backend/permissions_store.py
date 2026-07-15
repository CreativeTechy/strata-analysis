"""Postgres-backed roles & permissions: dynamic RBAC storage.

A role is a named, editable set of permission keys (e.g. "projects.view").
`full_access` roles (seeded only on 'admin') implicitly hold every permission
without needing rows in `role_permissions`, so they can't be locked out by
editing the permission matrix. `is_system` roles can't be deleted.
"""

from __future__ import annotations

import db

ROLE_SELECT = "id, name, description, is_system, full_access, created_at, updated_at"


def list_permissions():
    return db.fetch_all("select id, key, description from permissions order by key asc")


def list_roles():
    return db.fetch_all(f"select {ROLE_SELECT} from roles order by name asc")


def get_role_by_id(role_id):
    return db.fetch_one(f"select {ROLE_SELECT} from roles where id = %s limit 1", (role_id,))


def get_role_by_name(name: str):
    if not name:
        return None
    return db.fetch_one(f"select {ROLE_SELECT} from roles where lower(name) = lower(%s) limit 1", (name,))


def get_role_permission_keys(role_id) -> set:
    rows = db.fetch_all(
        """
        select p.key from role_permissions rp
        join permissions p on p.id = rp.permission_id
        where rp.role_id = %s
        """,
        (role_id,),
    )
    return {row["key"] for row in rows}


def get_role_with_permissions(role_id):
    role = get_role_by_id(role_id)
    if not role:
        return None
    if role.get("full_access"):
        perms = sorted(p["key"] for p in list_permissions())
    else:
        perms = sorted(get_role_permission_keys(role_id))
    return {**role, "permissions": perms}


def list_roles_with_permissions():
    all_keys = sorted(p["key"] for p in list_permissions())
    keys_by_role: dict = {}
    rows = db.fetch_all(
        """
        select rp.role_id, p.key from role_permissions rp
        join permissions p on p.id = rp.permission_id
        """
    )
    for row in rows:
        keys_by_role.setdefault(row["role_id"], set()).add(row["key"])
    return [
        {**role, "permissions": all_keys if role.get("full_access") else sorted(keys_by_role.get(role["id"], set()))}
        for role in list_roles()
    ]


def create_role(name: str, description: str | None = None, permission_keys=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("Role name is required.")
    row = db.fetch_one(
        "insert into roles (name, description) values (%s, %s) returning id",
        (name, (description or "").strip() or None),
    )
    if not row:
        return None
    if permission_keys is not None:
        set_role_permissions(row["id"], permission_keys)
    return get_role_with_permissions(row["id"])


def update_role(role_id, name: str | None = None, description: str | None = None):
    fields, params = [], []
    if name is not None:
        name = str(name).strip()
        if not name:
            raise ValueError("Role name is required.")
        fields.append("name = %s")
        params.append(name)
    if description is not None:
        fields.append("description = %s")
        params.append(str(description).strip() or None)
    if fields:
        fields.append("updated_at = now()")
        params.append(role_id)
        db.execute(f"update roles set {', '.join(fields)} where id = %s", tuple(params))
    return get_role_with_permissions(role_id)


def delete_role(role_id) -> bool:
    role = get_role_by_id(role_id)
    if not role:
        return False
    if role.get("is_system"):
        raise ValueError("This role is required by the system and cannot be deleted.")
    in_use = db.fetch_one("select count(*)::int as total from users where role_id = %s", (role_id,))
    if in_use and in_use.get("total"):
        raise ValueError("Cannot delete a role that is still assigned to users.")
    db.execute("delete from roles where id = %s", (role_id,))
    return True


def set_role_permissions(role_id, permission_keys) -> set:
    keys = sorted({str(k).strip() for k in (permission_keys or []) if str(k).strip()})
    db.execute("delete from role_permissions where role_id = %s", (role_id,))
    for key in keys:
        db.execute(
            """
            insert into role_permissions (role_id, permission_id)
            select %s, id from permissions where key = %s
            on conflict do nothing
            """,
            (role_id, key),
        )
    return get_role_permission_keys(role_id)


def user_permission_keys(user: dict) -> set:
    role_id = user.get("role_id") if user else None
    if not role_id:
        return set()
    role = get_role_by_id(role_id)
    if not role:
        return set()
    if role.get("full_access"):
        return {p["key"] for p in list_permissions()}
    return get_role_permission_keys(role_id)
