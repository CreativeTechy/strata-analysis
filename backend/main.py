"""FastAPI service that orchestrates the pipeline.

The four stages live in their own modules:
  scraper  -> scraper/spiders/source_rss.py (Scrapy)
  enricher -> enrich.py
  saver    -> store.py

This API triggers the jobs and exposes configured sources to the dashboard.
"""

import asyncio
import contextlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

import config
import permissions_store
import sessions_store
import users_store
from auth import clear_auth_cookies, get_current_user, require_any_permission, require_permission, set_auth_cookies
from project_discovery import discover_project_links
from projects_ai import suggest_project_metadata
from articles_store import compute_overall_tone, export_articles, get_article_stats, list_articles
from llm_client import chat_completion
from projects_store import (
    create_project,
    delete_project,
    diagnose_project_setup,
    list_project_ids_for_user,
    list_projects,
    list_projects_page,
    list_sources_for_project,
    persist_project_embedding_for_id,
    project_ids_by_user_map,
    record_run_completion,
    set_project_sources,
    set_project_users,
    update_project,
)
from sources_store import (
    bootstrap_sources,
    create_source,
    delete_source,
    diagnose_source_setup,
    list_sources_page,
    update_source,
)
from pipeline import cancel_pipeline_run, run_scraper_pipeline
from pipeline_runs import (
    ACTIVE_STATUSES,
    create_pipeline_run,
    get_active_run_for_project,
    get_pipeline_run,
    list_pipeline_runs,
    update_pipeline_run,
)
from scheduler import scheduler_loop

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR.parent / "storage"


def _load_text_asset(filename, fallback=""):
    path = STORAGE_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return fallback.strip()


COPILOT_SYSTEM_PROMPT = _load_text_asset("copilot_system_prompt.txt")

app = FastAPI(title="Strata Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

    hashtags = project.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = [hashtags]
    hashtags = [str(item).strip() for item in hashtags if str(item).strip()]
    if hashtags:
        parts.append(f"Hashtags: {', '.join(hashtags)}")

    keywords = project.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [str(item).strip() for item in keywords if str(item).strip()]
    if keywords:
        parts.append(f"Keywords: {', '.join(keywords)}")

    usernames = project.get("usernames") or []
    if isinstance(usernames, str):
        usernames = [usernames]
    usernames = [str(item).strip() for item in usernames if str(item).strip()]
    if usernames:
        parts.append(f"Usernames: {', '.join(usernames)}")

    first_run_at = project.get("first_run_at")
    if first_run_at:
        parts.append(f"First run at: {first_run_at}")

    description = (project.get("description") or "").strip()
    if description:
        parts.append(f"Description: {description}")

    return "\n".join(parts)


@app.on_event("startup")
async def _bootstrap_admin():
    users_store.bootstrap_admin()


@app.on_event("startup")
async def _start_scheduler():
    app.state.scheduler_task = asyncio.create_task(scheduler_loop())


@app.on_event("shutdown")
async def _stop_scheduler():
    task = getattr(app.state, "scheduler_task", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@app.get("/")
def root():
    return {"service": "Strata Media API", "ok": True, "see": "/api/health"}


@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "Strata Scraper API"}


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


@app.get("/api/sources")
def get_sources(limit: int | None = None, offset: int = 0, user: dict = Depends(require_permission("sources.view"))):
    """Configured sources for the dashboard sidebar."""
    if limit is None:
        sources = bootstrap_sources()
        source = sources[0].get("source", "database") if sources else "database"
        return {"sources": sources, "source": source}

    page = list_sources_page(limit=limit, offset=offset)
    source = page["sources"][0].get("source", "database") if page["sources"] else "database"
    return {**page, "source": source}


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


def _default_discovery_result(project):
    source_ids = []
    for value in project.get("source_ids") or []:
        try:
            source_ids.append(int(value))
        except Exception:
            continue
    return {
        "search_terms": [],
        "candidates": [],
        "suggested_links": [],
        "source_ids": source_ids,
        "sources": [],
    }


def _save_project_with_discovery(project):
    if not isinstance(project, dict):
        return None, {}

    discovery = (
        discover_project_links(project)
        if (project.get("hashtags") or project.get("keywords") or project.get("usernames"))
        else _default_discovery_result(project)
    )
    if discovery.get("source_ids") is not None:
        project = {**project, "source_ids": discovery.get("source_ids") or project.get("source_ids") or []}
    return project, discovery


@app.post("/api/projects/discover")
def discover_project(payload: dict, user: dict = Depends(require_permission("projects.create"))):
    if not isinstance(payload, dict):
        payload = {}
    discovery = discover_project_links(payload)
    return {"discovery": discovery}


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
    project, discovery = _save_project_with_discovery(project)
    return {"project": project, "discovery": discovery}


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
def get_pipeline_runs(limit: int = 10, user: dict = Depends(require_permission("pipeline.view"))):
    return {"runs": list_pipeline_runs(limit=max(1, min(int(limit), 25)))}


@app.post("/api/pipeline-runs/{run_id}/stop")
def stop_pipeline_run(run_id: str, user: dict = Depends(require_permission("pipeline.stop"))):
    run = get_pipeline_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found.")

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

    return {"run": updated or run, "message": "Pipeline run cancelled."}


@app.get("/api/articles")
def get_articles(
    search: str | None = None,
    sentiment: str | None = None,
    category: str | None = None,
    project_id: int | None = None,
    limit: int = 24,
    offset: int = 0,
    sort: str = "published.desc",
    user: dict = Depends(require_permission("articles.view")),
):
    return list_articles(
        search=search,
        sentiment=sentiment,
        category=category,
        project_id=project_id,
        limit=limit,
        offset=offset,
        sort=sort,
    )


@app.get("/api/articles/stats")
def get_articles_stats(
    search: str | None = None,
    category: str | None = None,
    project_id: int | None = None,
    user: dict = Depends(require_permission("articles.view")),
):
    return get_article_stats(search=search, category=category, project_id=project_id)


@app.get("/api/articles/export")
def export_articles_jsonl(
    search: str | None = None,
    sentiment: str | None = None,
    category: str | None = None,
    project_id: int | None = None,
    sort: str = "published.desc",
    user: dict = Depends(require_permission("articles.view")),
):
    rows = export_articles(
        search=search,
        sentiment=sentiment,
        category=category,
        project_id=project_id,
        sort=sort,
    )

    def line_stream():
        for row in rows:
            yield json.dumps(row, ensure_ascii=False, default=str) + "\n"

    filename = "articles-export.jsonl"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": "application/x-ndjson; charset=utf-8",
    }
    return StreamingResponse(line_stream(), headers=headers, media_type="application/x-ndjson")


@app.post("/api/sources")
def add_source(payload: dict, user: dict = Depends(require_permission("sources.create"))):
    """Create or update a source record in local PostgreSQL."""
    source = create_source(payload or {})
    if not source:
        detail = diagnose_source_setup()
        return {
            "error": "Unable to create source. Check database connection settings.",
            "detail": detail or "The source request did not return a row.",
        }
    return {"source": source}


@app.put("/api/sources/{source_id}")
def edit_source(source_id: int, payload: dict, user: dict = Depends(require_permission("sources.update"))):
    """Update a source record in local PostgreSQL."""
    source = update_source(source_id, payload or {})
    if not source:
        detail = diagnose_source_setup()
        return {
            "error": "Unable to update source. Check database connection settings.",
            "detail": detail or "The update request did not return a row.",
        }
    return {"source": source}


@app.delete("/api/sources/{source_id}")
def remove_source(source_id: int, user: dict = Depends(require_permission("sources.delete"))):
    """Delete a source record from local PostgreSQL."""
    if not delete_source(source_id):
        detail = diagnose_source_setup()
        return {
            "error": "Unable to delete source. Check database connection settings.",
            "detail": detail or "The delete request failed.",
        }
    return {"ok": True}


@app.post("/api/projects/{project_id}/sources")
def replace_project_sources(project_id: int, payload: dict, user: dict = Depends(require_permission("projects.update"))):
    _ensure_project_visible(project_id, user)
    source_ids = payload.get("source_ids") if isinstance(payload, dict) else []
    assigned = set_project_sources(project_id, source_ids or [])
    return {"project_id": project_id, "source_ids": assigned}


@app.post("/api/projects/{project_id}/users")
def replace_project_users(project_id: int, payload: dict, user: dict = Depends(require_permission("projects.link_users"))):
    _ensure_project_visible(project_id, user)
    user_ids = payload.get("user_ids") if isinstance(payload, dict) else []
    assigned = set_project_users(project_id, user_ids or [])
    return {"project_id": project_id, "user_ids": assigned}


@app.post("/scrape")
def trigger_scrape(background_tasks: BackgroundTasks, payload: dict | None = None, user: dict = Depends(require_permission("pipeline.run"))):
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
            raise HTTPException(status_code=400, detail="Create a project before running the scraper.")
        else:
            raise HTTPException(status_code=400, detail="Select a project before running the scraper.")

    if not list_sources_for_project(project_id):
        raise HTTPException(status_code=400, detail="Assign at least one source to the selected project before scraping.")

    active_run = get_active_run_for_project(project_id)
    if active_run:
        return {
            "message": "A pipeline run is already active for this project.",
            "run_id": active_run["id"],
            "project_id": project_id,
        }

    run = create_pipeline_run(status="queued", stage="queued", message="Queued for execution.", project_id=project_id)
    run_id = run["id"] if run else uuid.uuid4().hex
    background_tasks.add_task(run_scraper_pipeline, run_id, project_id)
    return {
        "message": "Scraper pipeline triggered. It will save to local PostgreSQL when finished.",
        "run_id": run_id,
        "project_id": project_id,
    }


@app.delete("/api/articles")
def delete_articles(user: dict = Depends(require_permission("articles.delete"))):
    """Delete all stored articles from Postgres."""
    from store import delete_all_articles

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
    """Intelligence Copilot -> DeepSeek over the filtered articles."""
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
            timeout=60,
        )
        return {"reply": reply}
    except Exception as e:
        return {"error": f"LLM request failed: {e}"}
