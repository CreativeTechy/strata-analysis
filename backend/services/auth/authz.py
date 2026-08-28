"""Project-visibility scoping, shared by every router that takes a project id.

Distinct from services/auth/auth.py's require_permission(): that answers "is
this user allowed to perform this *kind* of action at all" (RBAC), while this
answers "can this specific user see *this* project" (per-user linkage via
project_users). A route needs both - permission alone lets any user with,
say, articles.view read any project's data regardless of which projects they
are actually linked to.

Originally lived as two private functions in main.py; pulled out so
services/projects/project_documents_api.py and
services/competitors/competitor_api.py - routers main.py mounts but does not
otherwise share code with - can apply the same check instead of skipping it.
"""

from __future__ import annotations

from fastapi import HTTPException

from services.auth import permissions_store
from services.projects.projects_store import list_project_ids_for_user


def visible_project_ids_or_none(user: dict):
    """None means "no restriction" (admin/full_access); otherwise the list of
    project ids this user is linked to via project_users."""
    if permissions_store.user_is_full_access(user):
        return None
    return list_project_ids_for_user(user["id"])


def ensure_project_visible(project_id: int, user: dict) -> None:
    """Defense-in-depth for project-scoped mutations: a non-admin acting on a
    project they can't see gets a 404, same as if it didn't exist."""
    if permissions_store.user_is_full_access(user):
        return
    if int(project_id) not in set(list_project_ids_for_user(user["id"])):
        raise HTTPException(status_code=404, detail="Project not found.")
