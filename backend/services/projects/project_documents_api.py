"""HTTP surface for offline (document-upload) opinion-monitor projects.

Kept in its own APIRouter rather than appended to main.py, mirroring
services/competitors/competitor_api.py's document endpoints - same shape,
same reasoning (upload/extraction is a distinct enough concern to keep out of
main.py's growing route list), but writing to project_documents/
project_document_articles instead of the competitor-study tables, and ending
in a tracked analysis run rather than a competitor-findings run.

Extraction and article-splitting both run as FastAPI BackgroundTasks - OCR on
a scanned PDF, and the LLM call that splits text into candidates, can both run
well past a request's gateway timeout. The wizard polls GET .../documents and
GET .../document-articles for progress, same as the competitor wizard does.

An uploaded .json/.jsonl/.ndjson (a JSONL export from GET /api/articles/export,
or any list of article-shaped objects) is one of these documents like any
other - it just takes the no-OCR, no-LLM branch of process_document. There is
no separate import endpoint here on purpose: the review-then-approve step is
the whole point of this wizard, and a second path into `articles` would skip it.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from services.auth.auth import require_permission
from services.auth.authz import ensure_project_visible
from services.pipeline.pipeline import start_or_reuse_analysis_run
from services.projects import project_document_articles, project_documents_store
from services.projects.projects_store import get_project

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _project_or_404(project_id: int, user: dict) -> dict:
    """Same "can't see it, so it doesn't exist" shape as main.py's project
    routes: 404 rather than 403 for a project outside this user's
    project_users links, not just a permission check on the route itself."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_project_visible(project_id, user)
    return project


def _document_or_404(document_id: int, user: dict) -> dict:
    """Same visibility check as _project_or_404, resolved from the document's
    own project_id - every document-id-scoped route below takes an id with no
    project_id in the path, so it can't rely on the caller having already
    proven visibility the way the project-id-scoped routes can."""
    document = project_documents_store.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    ensure_project_visible(document["project_id"], user)
    return document


# --------------------------------------------------------------------------- #
# Documents (offline projects) - upload, then extract text in the background.
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/documents")
def list_documents(project_id: int, user: dict = Depends(require_permission("projects.view"))):
    """Poll this while any document's status is 'uploaded'/'processing', or
    articles_status is 'generating' — those are the only progress signals
    extraction/splitting have, no separate run-tracking object needed."""
    _project_or_404(project_id, user)
    return {"documents": project_documents_store.list_documents(project_id)}


@router.get("/documents/{document_id}/text")
def get_document_text(document_id: int, user: dict = Depends(require_permission("projects.view"))):
    _document_or_404(document_id, user)
    text = project_documents_store.get_document_text(document_id)
    if text is None:
        raise HTTPException(status_code=404, detail="No extracted text for this document.")
    return {"text": text}


@router.get("/documents/{document_id}/chunks")
def list_document_chunks(document_id: int, user: dict = Depends(require_permission("projects.view"))):
    """Per-page/sheet detail behind a document's rolled-up status and
    extraction_error — which part failed and why, not just that something did."""
    _document_or_404(document_id, user)
    return {"chunks": project_documents_store.list_chunks(document_id)}


@router.post("/{project_id}/documents")
async def upload_documents(
    project_id: int,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    user: dict = Depends(require_permission("projects.update")),
):
    """Save uploaded documents for an offline project and queue extraction for
    each. The response returns as soon as files are saved; the wizard polls
    GET .../documents for extraction status."""
    _project_or_404(project_id, user)
    if not files:
        raise HTTPException(status_code=400, detail="Choose at least one file to upload.")
    if len(files) > project_documents_store.MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"Upload at most {project_documents_store.MAX_FILES_PER_UPLOAD} files at a time.",
        )
    for upload in files:
        if not project_documents_store.extension_allowed(upload.filename):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{upload.filename}' isn't a supported type "
                    "(pdf, doc, docx, xls, xlsx, csv, png, jpg, jpeg, json, jsonl, ndjson)."
                ),
            )

    saved = []
    for upload in files:
        content = await upload.read()
        if len(content) > project_documents_store.MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=400, detail=f"'{upload.filename}' is larger than 25 MB.")
        record = project_documents_store.save_document(
            project_id, filename=upload.filename, content=content, mime_type=upload.content_type
        )
        if record:
            saved.append(record)
            background_tasks.add_task(project_documents_store.process_document, record["id"])

    if not saved:
        raise HTTPException(status_code=500, detail="Could not save the uploaded documents.")
    return {"documents": saved}


@router.delete("/documents/{document_id}")
def remove_document(document_id: int, user: dict = Depends(require_permission("projects.update"))):
    _document_or_404(document_id, user)
    if not project_documents_store.delete_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Document articles - candidates split out of a document's extracted text,
# reviewed and approved before they become real (sentiment-analyzed) articles.
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/document-articles")
def list_document_articles(project_id: int, user: dict = Depends(require_permission("projects.view"))):
    """Each row's article_analysis_status reflects the materialized article's
    own analysis_status (pending/processing/success/failed), so the wizard can
    show per-article progress without a separate polling endpoint."""
    _project_or_404(project_id, user)
    return {"articles": project_document_articles.list_candidates(project_id)}


@router.post("/document-articles/{candidate_id}/status")
def set_document_article_status(
    candidate_id: int,
    payload: dict,
    user: dict = Depends(require_permission("projects.update")),
):
    """Approving materializes the candidate into a real `articles` row (see
    project_document_articles._materialize) and starts a tracked analysis run
    (or joins whichever one is already active) so it shows up on the Analysis
    Runs page; rejecting just marks it. Re-approving an already-approved
    candidate is a no-op on the article itself - only a first approval starts
    a run."""
    status = str((payload or {}).get("status") or "").strip().lower()
    existing = project_document_articles.get_candidate(candidate_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Document article not found")
    ensure_project_visible(existing["project_id"], user)
    had_article_id = bool(existing.get("article_id"))

    candidate = project_document_articles.set_status(candidate_id, status)
    if not candidate:
        raise HTTPException(status_code=400, detail="status must be pending, approved, or rejected.")

    run_id = None
    if status == "approved" and not had_article_id and candidate.get("article_id"):
        run_id = start_or_reuse_analysis_run(existing["project_id"])["run_id"]
    return {"article": candidate, "run_id": run_id}


@router.post("/{project_id}/document-articles/approve-all")
def approve_all_document_articles(
    project_id: int,
    user: dict = Depends(require_permission("projects.update")),
):
    _project_or_404(project_id, user)
    approved = project_document_articles.approve_all(project_id)
    run_id = None
    if any(candidate.get("article_id") for candidate in approved):
        run_id = start_or_reuse_analysis_run(project_id)["run_id"]
    return {"articles": approved, "run_id": run_id}


@router.post("/{project_id}/document-articles/reanalyze")
def reanalyze_document_articles(
    project_id: int,
    user: dict = Depends(require_permission("projects.update")),
):
    """Re-run analysis for the approved candidates whose articles haven't been
    analyzed successfully - a manual retry for whichever ones failed. Same
    tracked run as approving a candidate goes through (see
    set_document_article_status / approve_all_document_articles) - this is
    just the retry entry point for when nothing is left to approve.
    """
    _project_or_404(project_id, user)
    if not project_document_articles.approved_article_ids(project_id):
        return {"run_id": None, "queued": 0, "message": "No approved articles to analyze yet."}

    run_info = start_or_reuse_analysis_run(project_id)
    if not run_info["started"]:
        return {"run_id": run_info["run_id"], "queued": 0, "message": "An analysis run is already active for this project."}
    return {"run_id": run_info["run_id"], "message": "Analysis run started."}
