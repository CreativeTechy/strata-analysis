"""FastAPI service behind the dashboard.

Everything the app analyzes is uploaded, not fetched: documents come in through
services/projects/project_documents_api.py (opinion monitor) and
services/competitors/competitor_api.py (competitor studies), are split into
articles, and are analyzed by the AI stage pipeline in backend/analysis/.

This module owns auth, users/roles, projects, articles, analysis runs, and the
Intelligence Copilot; the two document domains keep their own routers.
"""

import contextlib
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

import config
import migrate
from prompt_loader import load_prompt
from services.competitors import competitor_api
from services.projects import project_documents_api
from services.auth import permissions_store
from services.auth import sessions_store
from services.auth import users_store
from services.auth.auth import clear_auth_cookies, get_current_user, require_any_permission, require_permission, set_auth_cookies
from services.projects.projects_ai import suggest_project_metadata
from services.articles.articles_store import (
    compute_overall_tone,
    export_articles,
    get_analysis_status_counts,
    get_article_analysis,
    get_article_stats,
    list_analysis_errors,
    list_articles,
    list_articles_for_idea_cluster,
    list_idea_clusters_for_project,
)
from services.articles.import_jobs import (
    create_import_run,
    get_import_run,
    run_import_job,
)
from services.articles.reanalyze import (
    load_article_for_reanalysis,
    mark_processing,
    mark_reprocess_requested,
    reanalyze_article,
    reanalyze_articles,
)
from llm_client import LLMError, chat_completion
from services.projects.projects_store import (
    create_project,
    delete_project,
    diagnose_project_setup,
    get_project,
    list_project_ids_for_user,
    list_projects,
    list_projects_page,
    persist_project_embedding_for_id,
    project_ids_by_user_map,
    record_run_completion,
    set_project_users,
    update_project,
)
from services.intelligence.intelligence import get_project_intelligence, get_project_keyword_existence, normalize_period
from services.intelligence.trend_summary import generate_trend_summary
from services.pipeline.pipeline import cancel_pipeline_run, run_analysis_pipeline
from services.pipeline.pipeline_runs import (
    ACTIVE_STATUSES,
    create_pipeline_run,
    delete_pipeline_run,
    get_active_run_for_project,
    get_pipeline_run,
    get_pipeline_run_documents,
    list_pipeline_runs,
    update_pipeline_run,
)

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR.parent / "storage"

COPILOT_SYSTEM_PROMPT = load_prompt("copilot_system_prompt.txt")

logger = logging.getLogger(__name__)

app = FastAPI(title="Strata Analysis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The competitor study is a separate experience from sentiment/opinions, so its
# routes live in their own module rather than growing this one.
app.include_router(competitor_api.router)
# Offline (document-upload) opinion-monitor projects - same reasoning as above.
app.include_router(project_documents_api.router)


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    # Shape every raised HTTPException (401/403/404/...) like this API's
    # existing ad hoc error bodies ({"error": ...}) so the dashboard's
    # shared formatApiError() handles them without special-casing.
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


def _format_project_context(project: dict | None) -> str:
    if not isinstance(project, dict):
        return ""

    parts = []
    name = (project.get("name") or "").strip()
    if name:
        parts.append(f"Name: {name}")

    status = (project.get("status") or "").strip()
    if status:
        parts.append(f"Status: {status}")

    start_date = project.get("start_date")
    if start_date:
        parts.append(f"Start date: {start_date}")

    end_date = project.get("end_date")
    if end_date:
        parts.append(f"End date: {end_date}")

    location = (project.get("location") or "").strip()
    if location:
        parts.append(f"Location: {location}")

    location_type = (project.get("location_type") or "").strip()
    if location_type:
        parts.append(f"Location type: {location_type}")

    target_audience = (project.get("target_audience") or "").strip()
    if target_audience:
        parts.append(f"Target audience: {target_audience}")

    keywords = project.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [str(item).strip() for item in keywords if str(item).strip()]
    if keywords:
        parts.append(f"Topics of interest: {', '.join(keywords)}")

    description = (project.get("description") or "").strip()
    if description:
        parts.append(f"Description: {description}")

    return "\n".join(parts)


@app.on_event("startup")
async def _apply_migrations():
    """Bring the schema up to date before anything reads or writes it.

    Registered ahead of the admin bootstrap on purpose: that depends on roles the
    baseline migration seeds. Failures are deliberately fatal — a backend serving
    requests against a schema it does not match returns wrong answers silently,
    which is worse than refusing to start. Set MIGRATE_ON_STARTUP=false to manage
    migrations out of band (`python migrate.py`) instead.
    """
    if not config.MIGRATE_ON_STARTUP:
        logger.info("Startup migrations disabled (MIGRATE_ON_STARTUP=false).")
        return
    if not config.DATABASE_URL:
        logger.warning("DATABASE_URL is missing; skipping migrations.")
        return
    migrate.run_on_startup()


@app.on_event("startup")
async def _bootstrap_admin():
    users_store.bootstrap_admin()


@app.get("/")
def root():
    return {"service": "Strata Analysis API", "ok": True, "see": "/api/health"}


@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "Strata Analysis API"}


# --- Auth --------------------------------------------------------------


def _public_user(user: dict) -> dict:
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "email": user.get("email"),
        "role": user.get("role"),
        "status": user.get("status"),
        "permissions": sorted(permissions_store.user_permission_keys(user)),
    }


@app.post("/api/auth/login")
def login(payload: dict, response: Response):
    payload = payload or {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")

    row = users_store.get_user_by_login(username)
    if not row or row.get("status") != "active" or not users_store.verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    raw_token, csrf_token, expires_at = sessions_store.create_session(row["id"])
    users_store.record_login(row["id"])
    set_auth_cookies(response, raw_token, csrf_token, expires_at)
    return {"user": _public_user(row)}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, user: dict = Depends(require_permission())):
    raw_token = request.cookies.get(config.SESSION_COOKIE_NAME)
    sessions_store.delete_session(raw_token)
    clear_auth_cookies(response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    return {"user": _public_user(user)}


# --- User management ------------------------------------------------------


@app.get("/api/users/linkable")
def get_linkable_users(user: dict = Depends(require_permission("projects.link_users"))):
    """Roster used by the project<->user linkage UI - gated only by
    projects.link_users so it works for admins who manage linkage without
    also holding users.view."""
    project_ids_by_user = project_ids_by_user_map()
    users = [
        {**candidate, "project_ids": project_ids_by_user.get(int(candidate["id"]), [])}
        for candidate in users_store.list_users()
    ]
    return {"users": users}


@app.get("/api/users")
def get_users(user: dict = Depends(require_permission("users.view"))):
    return {"users": users_store.list_users()}


@app.post("/api/users")
def add_user(payload: dict, user: dict = Depends(require_permission("users.create"))):
    payload = payload or {}
    username = str(payload.get("username") or "").strip()
    email = str(payload.get("email") or "").strip()
    password = str(payload.get("password") or "")
    role_name = str(payload.get("role") or "viewer").strip().lower()

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    role = permissions_store.get_role_by_name(role_name)
    if not role:
        raise HTTPException(status_code=400, detail=f"Unknown role: {role_name}")

    try:
        created = users_store.create_user(username, email, password, role["id"])
    except Exception as e:
        raise HTTPException(status_code=409, detail=f"Unable to create user: {e}")
    if not created:
        raise HTTPException(status_code=409, detail="Unable to create user.")
    return {"user": created}


@app.patch("/api/users/{user_id}")
def edit_user(user_id: int, payload: dict, user: dict = Depends(require_permission("users.update"))):
    payload = payload or {}
    role_name = payload.get("role")
    status = payload.get("status")
    if role_name is not None:
        role_name = str(role_name).strip().lower()
    if status is not None:
        status = str(status).strip().lower()

    if user_id == user["id"] and (role_name is not None or status == "disabled"):
        raise HTTPException(status_code=400, detail="You cannot change your own role or disable yourself.")

    role_id = None
    if role_name is not None:
        role = permissions_store.get_role_by_name(role_name)
        if not role:
            raise HTTPException(status_code=400, detail=f"Unknown role: {role_name}")
        role_id = role["id"]

    try:
        updated = users_store.update_user(user_id, role_id=role_id, status=status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not updated:
        raise HTTPException(status_code=404, detail="User not found.")
    if status == "disabled":
        sessions_store.delete_sessions_for_user(user_id)
    return {"user": updated}


@app.delete("/api/users/{user_id}")
def remove_user(user_id: int, user: dict = Depends(require_permission("users.delete"))):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="You cannot delete your own account.")
    sessions_store.delete_sessions_for_user(user_id)
    deleted = users_store.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"ok": True}


# --- Role management --------------------------------------------------------


@app.get("/api/permissions")
def get_permissions(user: dict = Depends(require_permission("roles.view"))):
    return {"permissions": permissions_store.list_permissions()}


@app.get("/api/roles")
def get_roles(user: dict = Depends(require_permission("roles.view"))):
    return {"roles": permissions_store.list_roles_with_permissions()}


@app.post("/api/roles")
def add_role(payload: dict, user: dict = Depends(require_permission("roles.create"))):
    payload = payload or {}
    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    permission_keys = payload.get("permissions") or []
    if not name:
        raise HTTPException(status_code=400, detail="Role name is required.")

    try:
        role = permissions_store.create_role(name, description, permission_keys)
    except Exception as e:
        raise HTTPException(status_code=409, detail=f"Unable to create role: {e}")
    if not role:
        raise HTTPException(status_code=409, detail="Unable to create role.")
    return {"role": role}


@app.patch("/api/roles/{role_id}")
def edit_role(role_id: int, payload: dict, user: dict = Depends(require_permission("roles.update"))):
    payload = payload or {}
    name = payload.get("name")
    description = payload.get("description")
    permission_keys = payload.get("permissions")

    role = permissions_store.get_role_by_id(role_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found.")

    try:
        if name is not None or description is not None:
            permissions_store.update_role(role_id, name=name, description=description)
        if permission_keys is not None and not role.get("full_access"):
            permissions_store.set_role_permissions(role_id, permission_keys)
    except Exception as e:
        raise HTTPException(status_code=409, detail=f"Unable to update role: {e}")

    return {"role": permissions_store.get_role_with_permissions(role_id)}


@app.delete("/api/roles/{role_id}")
def remove_role(role_id: int, user: dict = Depends(require_permission("roles.delete"))):
    try:
        deleted = permissions_store.delete_role(role_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Role not found.")
    return {"ok": True}


def _visible_project_ids_or_none(user: dict):
    """None means "no restriction" (admin/full_access); otherwise the list of
    project ids this user is linked to via project_users."""
    if permissions_store.user_is_full_access(user):
        return None
    return list_project_ids_for_user(user["id"])


def _ensure_project_visible(project_id: int, user: dict) -> None:
    """Defense-in-depth for project-scoped mutations: a non-admin acting on a
    project they can't see gets a 404, same as if it didn't exist."""
    if permissions_store.user_is_full_access(user):
        return
    if int(project_id) not in set(list_project_ids_for_user(user["id"])):
        raise HTTPException(status_code=404, detail="Project not found.")


@app.get("/api/projects")
def get_projects(limit: int | None = None, offset: int = 0, user: dict = Depends(require_permission("projects.view"))):
    visible_ids = _visible_project_ids_or_none(user)
    if limit is None:
        return {"projects": list_projects(visible_project_ids=visible_ids)}
    return list_projects_page(limit=limit, offset=offset, visible_project_ids=visible_ids)


def _strip_unauthorized_user_ids(payload: dict, user: dict) -> dict:
    """Drop `user_ids` from a project payload unless the caller holds
    projects.link_users, so link management stays gated to that permission
    even though project create/update itself only needs projects.create/update."""
    if not isinstance(payload, dict) or "user_ids" not in payload:
        return payload or {}
    if "projects.link_users" in permissions_store.user_permission_keys(user):
        return payload
    payload = dict(payload)
    payload.pop("user_ids", None)
    return payload


@app.post("/api/projects")
def add_project(background_tasks: BackgroundTasks, payload: dict, user: dict = Depends(require_permission("projects.create"))):
    payload = _strip_unauthorized_user_ids(payload, user)
    try:
        project = create_project(payload or {}, embed=False)
    except ValueError as e:
        return {"error": "Invalid project payload.", "detail": str(e)}
    except Exception as e:
        detail = diagnose_project_setup()
        return {
            "error": "Unable to create project. Check database connection settings.",
            "detail": detail or str(e),
        }
    if not project:
        detail = diagnose_project_setup()
        return {
            "error": "Unable to create project. Check database connection settings.",
            "detail": detail or "The project request did not return a row.",
        }
    background_tasks.add_task(persist_project_embedding_for_id, project.get("id"))
    return {"project": project}


@app.put("/api/projects/{project_id}")
def edit_project(project_id: int, background_tasks: BackgroundTasks, payload: dict, user: dict = Depends(require_permission("projects.update"))):
    _ensure_project_visible(project_id, user)
    payload = _strip_unauthorized_user_ids(payload, user)
    try:
        project = update_project(project_id, payload or {}, embed=False)
    except ValueError as e:
        return {"error": "Invalid project payload.", "detail": str(e)}
    except Exception as e:
        detail = diagnose_project_setup()
        return {
            "error": "Unable to update project. Check database connection settings.",
            "detail": detail or str(e),
        }
    if not project:
        detail = diagnose_project_setup()
        return {
            "error": "Unable to update project. Check database connection settings.",
            "detail": detail or "The update request did not return a row.",
        }
    background_tasks.add_task(persist_project_embedding_for_id, project_id)
    return {"project": project}


@app.post("/api/projects/suggest")
def suggest_project(payload: dict, user: dict = Depends(require_any_permission("projects.create", "projects.update"))):
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    if not name:
        return {
            "error": "Project name is required.",
            "detail": "Provide the project name before requesting AI suggestions.",
        }
    return {"suggestions": suggest_project_metadata(name, description)}


@app.delete("/api/projects/{project_id}")
def remove_project(project_id: int, user: dict = Depends(require_permission("projects.delete"))):
    _ensure_project_visible(project_id, user)
    if not delete_project(project_id):
        detail = diagnose_project_setup()
        return {
            "error": "Unable to delete project. Check database connection settings.",
            "detail": detail or "The delete request failed.",
        }
    return {"ok": True}


@app.get("/api/pipeline-runs")
def get_pipeline_runs(
    limit: int = 10,
    project_id: int | None = None,
    user: dict = Depends(require_permission("pipeline.view")),
):
    return {"runs": list_pipeline_runs(limit=max(1, min(int(limit), 500)), project_id=project_id)}


@app.get("/api/pipeline-runs/{run_id}")
def get_pipeline_run_detail(run_id: str, user: dict = Depends(require_permission("pipeline.view"))):
    run = get_pipeline_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    return {"run": run, "documents": get_pipeline_run_documents(run_id) if run.get("has_detail") else []}


@app.post("/api/pipeline-runs/{run_id}/stop")
def stop_pipeline_run(run_id: str, user: dict = Depends(require_permission("pipeline.stop"))):
    run = get_pipeline_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found.")

    if run["status"] not in ACTIVE_STATUSES:
        return {"run": run, "message": f"Run is already {run['status']}; nothing to stop."}

    cancel_pipeline_run(run_id)

    now = datetime.now(timezone.utc).isoformat()
    updated = update_pipeline_run(
        run_id,
        status="cancelled",
        stage="cancelled",
        message="Cancelled by user.",
        cancel_requested_at=now,
        cancelled_at=now,
        finished_at=now,
    )
    if run.get("project_id") is not None:
        record_run_completion(run["project_id"], status="cancelled", completed_at=datetime.now(timezone.utc))

    return {"run": updated or run, "message": "Analysis run cancelled."}


@app.delete("/api/pipeline-runs/{run_id}")
def delete_pipeline_run_endpoint(
    run_id: str,
    user: dict = Depends(require_permission("pipeline.delete")),
):
    """Remove an analysis run from the history.

    This deletes the run and what was recorded about it - its per-document
    breakdown and its per-article analysis snapshots - so it stops appearing as
    a comparison point on the dashboard. The articles and the analysis currently
    stored on them are left alone; see delete_pipeline_run() for why.

    A run that is still queued/running is refused rather than stopped
    implicitly: its worker thread would otherwise keep writing progress into a
    row that no longer exists.
    """
    from services.articles.article_analyses import run_article_count

    run = get_pipeline_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Analysis run not found.")

    if run.get("project_id") is not None:
        _ensure_project_visible(run["project_id"], user)

    snapshots = run_article_count(run_id)
    try:
        deleted = delete_pipeline_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail="Analysis run not found.")

    return {
        "message": "Analysis run deleted.",
        "run_id": run_id,
        "snapshots_deleted": snapshots,
    }


@app.get("/api/articles")
def get_articles(
    search: str | None = None,
    sentiment: str | None = None,
    category: str | None = None,
    project_id: int | None = None,
    source_url: str | None = None,
    limit: int = 24,
    offset: int = 0,
    sort: str = "published.desc",
    added_from: str | None = None,
    added_to: str | None = None,
    user: dict = Depends(require_permission("articles.view")),
):
    return list_articles(
        search=search,
        sentiment=sentiment,
        category=category,
        project_id=project_id,
        source_url=source_url,
        limit=limit,
        offset=offset,
        sort=sort,
        added_from=added_from,
        added_to=added_to,
    )


@app.get("/api/articles/stats")
def get_articles_stats(
    search: str | None = None,
    category: str | None = None,
    project_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict = Depends(require_permission("articles.view")),
):
    return get_article_stats(search=search, category=category, project_id=project_id, date_from=date_from, date_to=date_to)


@app.get("/api/projects/{project_id}/intelligence")
def get_project_intelligence_view(
    project_id: int,
    period: str = "30d",
    run_id: str | None = None,
    user: dict = Depends(require_permission("articles.view")),
):
    _ensure_project_visible(project_id, user)
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return get_project_intelligence(project, normalize_period(period), run_id=run_id)


@app.get("/api/projects/{project_id}/keyword-existence")
def get_project_keyword_existence_view(
    project_id: int,
    period: str = "30d",
    source_url: str | None = None,
    keyword: str | None = None,
    run_id: str | None = None,
    user: dict = Depends(require_permission("articles.view")),
):
    _ensure_project_visible(project_id, user)
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return get_project_keyword_existence(
        project, normalize_period(period), source_url=source_url, keyword=keyword, run_id=run_id,
    )


@app.get("/api/projects/{project_id}/trend-summary")
def get_project_trend_summary_view(
    project_id: int,
    period: str = "30d",
    run_id: str | None = None,
    user: dict = Depends(require_permission("articles.view")),
):
    """LLM-generated "overall trend" paragraph for the Reports page -> the
    configured LLM provider, over the same period/run-scoped articles the
    rest of the intelligence endpoints use."""
    _ensure_project_visible(project_id, user)
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    try:
        return generate_trend_summary(project, normalize_period(period), run_id=run_id)
    except LLMError as e:
        logger.warning("Trend summary generation failed (%s): %s", e.code, e.detail or e)
        return {"error": e.user_message, "error_code": e.code}
    except Exception:
        logger.exception("Trend summary generation failed unexpectedly")
        return {
            "error": "Something went wrong while generating the trend summary. Please try again.",
            "error_code": "llm_provider_error",
        }


@app.get("/api/articles/export")
def export_articles_jsonl(
    search: str | None = None,
    sentiment: str | None = None,
    category: str | None = None,
    project_id: int | None = None,
    source_url: str | None = None,
    sort: str = "published.desc",
    added_from: str | None = None,
    added_to: str | None = None,
    user: dict = Depends(require_permission("articles.view")),
):
    def line_stream():
        # export_articles() is a generator, so rows are read a page at a time
        # as the response is written - no project's worth of articles (each
        # carrying its full text and embedding) is ever held in memory at once.
        rows = export_articles(
            search=search,
            sentiment=sentiment,
            category=category,
            project_id=project_id,
            source_url=source_url,
            sort=sort,
            added_from=added_from,
            added_to=added_to,
        )
        for row in rows:
            yield json.dumps(row, ensure_ascii=False, default=str) + "\n"

    filename = "articles-export.jsonl"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "application/x-ndjson; charset=utf-8",
    }
    return StreamingResponse(line_stream(), headers=headers, media_type="application/x-ndjson")


MAX_IMPORT_BYTES = 256 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024


@app.post("/api/articles/import")
async def import_articles_jsonl(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    project_id: int | None = Form(None),
    user: dict = Depends(require_permission("articles.import")),
):
    """Queue a JSONL export produced by GET /api/articles/export for import.

    Restoring a project means an upsert per article, each of which also writes
    its project link, story group and idea clusters - minutes of work for a
    real export, well past any gateway timeout. So the request only spools the
    upload to disk and returns a run id; the work happens in
    import_jobs.run_import_job and the UI polls GET .../import/{run_id} for
    live counts and throughput. Same queued/poll shape as competitor discovery.

    Only what can be judged from the bytes themselves is rejected here, so an
    oversized or plainly wrong file still fails fast with a real status code.
    """
    if project_id is not None:
        _ensure_project_visible(project_id, user)

    handle, path = tempfile.mkstemp(prefix="articles-import-", suffix=".jsonl")
    total_bytes = 0
    total_lines = 0
    leading = b""
    last_byte = b""

    try:
        with os.fdopen(handle, "wb") as spool:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_IMPORT_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"File is larger than the {MAX_IMPORT_BYTES // (1024 * 1024)}MB import limit. "
                            "Split it and import in parts."
                        ),
                    )
                if len(leading) < 64:
                    leading += chunk[: 64 - len(leading)]
                # Counting newlines as they stream past costs nothing and gives
                # the job a record-count estimate for its percentage and ETA.
                total_lines += chunk.count(b"\n")
                last_byte = chunk[-1:]
                spool.write(chunk)
        if total_bytes and last_byte != b"\n":
            total_lines += 1

        if not total_bytes:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")
        if leading.lstrip()[:1] == b"[":
            raise HTTPException(
                status_code=400,
                detail="Expected JSON Lines (one article object per line), not a JSON array.",
            )
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(path)
        raise

    run_id = create_import_run(project_id=project_id, filename=file.filename or "", total_lines=total_lines)
    background_tasks.add_task(run_import_job, run_id, path, project_id)
    return {"run_id": run_id, "status": "queued", "total_lines": total_lines, "project_id": project_id}


@app.get("/api/articles/import/{run_id}")
def import_articles_status(run_id: str, user: dict = Depends(require_permission("articles.import"))):
    """Progress for one import job: counters, throughput and its live logs."""
    run = get_import_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Import run not found.")
    return {"run": run}


# --- Analysis pipeline: on-demand (re)analysis, status, ideas -------------

MAX_BATCH_ANALYZE_IDS = 50


@app.post("/api/articles/{article_id}/analyze")
def analyze_article_endpoint(
    article_id: int,
    background_tasks: BackgroundTasks,
    payload: dict | None = None,
    user: dict = Depends(require_permission("pipeline.run")),
):
    """Run the analysis pipeline for one already-scraped article. Skips
    articles that already completed successfully unless force=true is
    passed - use POST .../reprocess to always force a fresh run regardless
    of current status."""
    force = bool((payload or {}).get("force"))
    article = load_article_for_reanalysis(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found.")

    current = get_article_analysis(article_id)
    if current and current.get("analysis_status") == "success" and not force:
        return {"article_id": article_id, "status": "skipped", "reason": "already_analyzed", "analysis": current}

    mark_processing(article_id)
    background_tasks.add_task(reanalyze_article, article_id)
    return {"article_id": article_id, "status": "processing"}


@app.post("/api/articles/analyze")
def analyze_articles_endpoint(
    background_tasks: BackgroundTasks,
    payload: dict,
    user: dict = Depends(require_permission("pipeline.run")),
):
    """Batch version of the single-article analyze endpoint - queues
    analysis for up to MAX_BATCH_ANALYZE_IDS articles at once and returns
    immediately; poll GET /api/analysis/status or each article's
    GET .../analysis for progress."""
    payload = payload or {}
    raw_ids = payload.get("article_ids") or []
    force = bool(payload.get("force"))
    if not isinstance(raw_ids, list) or not raw_ids:
        raise HTTPException(status_code=400, detail="article_ids must be a non-empty list.")
    if len(raw_ids) > MAX_BATCH_ANALYZE_IDS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_BATCH_ANALYZE_IDS} article_ids per request.")
    try:
        article_ids = [int(i) for i in raw_ids]
    except Exception:
        raise HTTPException(status_code=400, detail="article_ids must be integers.")

    queued, skipped, not_found = [], [], []
    for article_id in article_ids:
        if not load_article_for_reanalysis(article_id):
            not_found.append(article_id)
            continue
        current = get_article_analysis(article_id)
        if current and current.get("analysis_status") == "success" and not force:
            skipped.append(article_id)
            continue
        mark_processing(article_id)
        queued.append(article_id)

    if queued:
        background_tasks.add_task(reanalyze_articles, queued)

    return {"queued": queued, "skipped": skipped, "not_found": not_found}


@app.post("/api/articles/{article_id}/reprocess")
def reprocess_article_endpoint(
    article_id: int,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_permission("pipeline.run")),
):
    """Always forces a fresh analysis run, regardless of current
    analysis_status - distinct from POST .../analyze, which skips articles
    that already succeeded."""
    if not load_article_for_reanalysis(article_id):
        raise HTTPException(status_code=404, detail="Article not found.")

    reprocess_requested_at = mark_reprocess_requested(article_id)
    background_tasks.add_task(reanalyze_article, article_id)
    return {"article_id": article_id, "status": "processing", "reprocess_requested_at": reprocess_requested_at}


@app.get("/api/articles/{article_id}/analysis")
def get_article_analysis_endpoint(article_id: int, user: dict = Depends(require_permission("articles.view"))):
    """Full analysis detail for one article: sentiment/tone/category with
    their confidence scores, per-stage model identifiers, and
    analysis_status/analysis_error so a failed or low-confidence result is
    never mistaken for a confident real one."""
    analysis = get_article_analysis(article_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Article not found.")
    return {"analysis": analysis}


@app.get("/api/analysis/status")
def get_analysis_status_endpoint(
    project_id: int | None = None,
    user: dict = Depends(require_permission("pipeline.view")),
):
    """Aggregate analysis_status counts (pending/processing/success/failed/
    partial), optionally scoped to a project."""
    if project_id is not None:
        _ensure_project_visible(project_id, user)
    counts = get_analysis_status_counts(project_id=project_id)
    return {"project_id": project_id, "counts": counts, "total": sum(counts.values())}


@app.get("/api/articles/analysis-errors")
def get_analysis_errors_endpoint(
    project_id: int | None = None,
    limit: int = 24,
    offset: int = 0,
    user: dict = Depends(require_permission("articles.view")),
):
    """Paginated list of articles whose most recent analysis run failed,
    with the stored error - the detail view behind the aggregate counts in
    GET /api/analysis/status."""
    if project_id is not None:
        _ensure_project_visible(project_id, user)
    return list_analysis_errors(project_id=project_id, limit=limit, offset=offset)


@app.get("/api/projects/{project_id}/idea-clusters")
def get_project_idea_clusters(
    project_id: int,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(require_permission("articles.view")),
):
    """Cross-article frequent-idea clusters for a project - the persisted,
    cross-run counterpart to the per-run rollup in insights.frequent_ideas."""
    _ensure_project_visible(project_id, user)
    if not get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    return list_idea_clusters_for_project(project_id, limit=limit, offset=offset)


@app.get("/api/projects/{project_id}/idea-clusters/{cluster_id}/articles")
def get_idea_cluster_articles(
    project_id: int,
    cluster_id: int,
    limit: int = 10,
    offset: int = 0,
    user: dict = Depends(require_permission("articles.view")),
):
    """Representative source articles for one idea cluster."""
    _ensure_project_visible(project_id, user)
    if not get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    page = list_articles_for_idea_cluster(cluster_id, project_id, limit=limit, offset=offset)
    if page is None:
        raise HTTPException(status_code=404, detail="Idea cluster not found.")
    return page


@app.post("/api/projects/{project_id}/users")
def replace_project_users(project_id: int, payload: dict, user: dict = Depends(require_permission("projects.link_users"))):
    _ensure_project_visible(project_id, user)
    user_ids = payload.get("user_ids") if isinstance(payload, dict) else []
    assigned = set_project_users(project_id, user_ids or [])
    return {"project_id": project_id, "user_ids": assigned}


@app.post("/api/analysis-runs")
def trigger_analysis_run(
    background_tasks: BackgroundTasks,
    payload: dict | None = None,
    user: dict = Depends(require_permission("pipeline.run")),
):
    """Start an analysis run for a project.

    `scope` is "pending" (default - only articles whose analysis hasn't
    succeeded yet) or "all" (re-analyze everything the project holds, e.g.
    after switching to a different local model).

    One run at a time per project: a second concurrent run would have both
    workers analyzing the same articles and writing over each other.
    """
    payload = payload or {}
    project_id = payload.get("project_id")
    try:
        project_id = int(project_id) if project_id is not None else None
    except Exception:
        project_id = None
    if project_id is None:
        projects = list_projects()
        if len(projects) == 1:
            project_id = projects[0].get("id")
        elif not projects:
            raise HTTPException(status_code=400, detail="Create a project before running an analysis.")
        else:
            raise HTTPException(status_code=400, detail="Select a project before running an analysis.")

    _ensure_project_visible(project_id, user)
    if not get_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")

    scope = str(payload.get("scope") or "pending").strip().lower()
    if scope not in {"pending", "all"}:
        raise HTTPException(status_code=400, detail="scope must be 'pending' or 'all'.")

    active_run = get_active_run_for_project(project_id)
    if active_run:
        return {
            "message": "An analysis run is already active for this project.",
            "run_id": active_run["id"],
            "project_id": project_id,
        }

    run = create_pipeline_run(status="queued", stage="queued", message="Queued for execution.", project_id=project_id)
    run_id = run["id"] if run else uuid.uuid4().hex
    background_tasks.add_task(run_analysis_pipeline, run_id, project_id, scope)
    return {
        "message": "Analysis run started.",
        "run_id": run_id,
        "project_id": project_id,
        "scope": scope,
    }


@app.delete("/api/articles")
def delete_articles(user: dict = Depends(require_permission("articles.delete"))):
    """Delete all stored articles from Postgres."""
    from services.articles.store import delete_all_articles

    deleted = delete_all_articles()
    if not deleted:
        detail = "Check database connection settings."
        return {
            "error": "Unable to delete articles.",
            "detail": detail,
        }
    return {"ok": True}


@app.post("/api/chat")
async def chat(payload: dict, user: dict = Depends(require_permission())):
    """Intelligence Copilot -> the configured LLM provider, over the filtered articles."""
    question = str(payload.get("question", "")).strip()[:2000]
    if not question:
        return {"error": "Empty question"}
    articles = (payload.get("articles") or [])[:80]
    total = int(payload.get("total") or len(articles))
    project = payload.get("project") if isinstance(payload, dict) else None
    if not isinstance(project, dict):
        project_id = payload.get("project_id") if isinstance(payload, dict) else None
        try:
            project_id = int(project_id) if project_id is not None else None
        except Exception:
            project_id = None
        project = None
        if project_id is not None:
            projects = list_projects()
            project = next((item for item in projects if int(item.get("id") or -1) == project_id), None)

    project_context = _format_project_context(project)

    def _article_tone_line(a):
        writer_tone = a.get('writer_tone') or (a.get('insight_json') or {}).get('writer_tone', 'neutral')
        article_tone = a.get('article_tone') or (a.get('insight_json') or {}).get('article_tone', 'neutral')
        overall_tone = compute_overall_tone(article_tone, writer_tone)
        return f"writer tone: {writer_tone} | article tone: {article_tone} | overall tone: {overall_tone}"

    context = "\n".join(
        f"{i + 1}. [{a.get('source', '?')} | {a.get('sentiment', 'neutral')} | "
        f"{a.get('article_category') or a.get('category', 'general_article')} | "
        f"{_article_tone_line(a)} | "
        f"score {a.get('relevance_score', '?')}] "
        f"{a.get('title', '')}\n   {a.get('summary', '') or (a.get('insight_json') or {}).get('summary', '')}"
        for i, a in enumerate(articles)
    )
    user_prompt = (
        (f"Project context:\n{project_context}\n\n" if project_context else "")
        + f"There are {total} articles in the current view.\n\n"
        + "Use the project context as background when interpreting sentiment, tone, and relevance.\n\n"
        + f"{context or '(none)'}\n\nQuestion: {question}"
    )

    try:
        reply = chat_completion(
            messages=[
                {"role": "system", "content": COPILOT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=700,
        )
        return {"reply": reply}
    except LLMError as e:
        logger.warning("Copilot chat failed (%s): %s", e.code, e.detail or e)
        return {"error": e.user_message, "error_code": e.code}
    except Exception:
        logger.exception("Copilot chat failed unexpectedly")
        return {
            "error": "Something went wrong while generating a response. Please try again.",
            "error_code": "llm_provider_error",
        }
