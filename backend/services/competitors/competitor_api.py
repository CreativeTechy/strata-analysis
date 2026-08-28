"""HTTP surface for the competitor study.

Kept in its own APIRouter rather than appended to main.py: this is a separate
experience from sentiment/opinions, and separating the routes is what keeps the
two from tangling as either one grows.

A study is built from uploaded documents: the files are extracted and split
into articles, the companies those articles are about are named by
document_analysis.py, and analysis writes one card per competitor. Both of the
long steps - extraction/splitting and analysis - run as background jobs the UI
polls, since either can run well past a gateway timeout.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from services.competitors import analysis_runs_store
from services.competitors import business_profile_store
from services.competitors import competitor_analysis
from services.competitors import competitor_document_articles
from services.competitors import competitor_documents_store
from services.competitors import competitors_store
from services.competitors import document_analysis
from services.competitors.countries import validate_countries
from services.auth.auth import require_permission
from services.auth.authz import ensure_project_visible, visible_project_ids_or_none
from services.projects.projects_store import delete_project, project_has_articles

router = APIRouter(prefix="/api/competitor", tags=["competitor"])


def _project_or_404(project_id: int, user: dict) -> dict:
    """Same "can't see it, so it doesn't exist" shape as main.py's project
    routes: 404 rather than 403 for a study outside this user's project_users
    links, not just a permission check on the route itself."""
    project = competitors_store.get_study(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_project_visible(project_id, user)
    return project


def _competitor_or_404(competitor_id: int, user: dict) -> dict:
    competitor = competitors_store.get_competitor(competitor_id)
    if not competitor:
        raise HTTPException(status_code=404, detail="Competitor not found")
    ensure_project_visible(competitor["project_id"], user)
    return competitor


def _document_or_404(document_id: int, user: dict) -> dict:
    """Same visibility check as _project_or_404, resolved from the document's
    own project_id - every document-id-scoped route below takes an id with no
    project_id in the path, so it can't rely on the caller having already
    proven visibility the way the study-id-scoped routes can."""
    document = competitor_documents_store.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    ensure_project_visible(document["project_id"], user)
    return document


# --------------------------------------------------------------------------- #
# Studies
# --------------------------------------------------------------------------- #
@router.get("/studies")
def list_studies(user: dict = Depends(require_permission("competitors.view"))):
    """Competitor-mode projects with enough summary to render the index."""
    return {"studies": competitors_store.list_studies(visible_project_ids=visible_project_ids_or_none(user))}


@router.get("/studies/{project_id}/findings/recent")
def list_recent_study_findings(
    project_id: int,
    limit: int = 10,
    offset: int = 0,
    user: dict = Depends(require_permission("competitors.view")),
):
    """Paginated findings for one study, highest impact first — powers the Dashboard/Reports pulse card."""
    _project_or_404(project_id, user)
    limit = max(1, min(int(limit), 50))
    offset = max(0, int(offset))
    findings, total = competitor_analysis.list_recent_findings(project_id, limit=limit, offset=offset)
    return {"findings": findings, "total": total}


@router.post("/studies")
def create_study(payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    """Create a competitor-mode project. The business profile is added next."""
    name = str((payload or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="A study name is required.")
    project = competitors_store.create_study(
        name,
        str((payload or {}).get("status") or "active"),
        str((payload or {}).get("description") or "").strip() or None,
    )
    if not project:
        raise HTTPException(status_code=500, detail="Could not create the study.")
    return {"study": project}


@router.get("/studies/{project_id}")
def get_study(project_id: int, user: dict = Depends(require_permission("competitors.view"))):
    project = _project_or_404(project_id, user)
    return {
        "study": project,
        "profile": business_profile_store.get_profile(project_id),
        "competitors": competitors_store.competitor_overview(project_id),
        "findings": competitor_analysis.list_findings(project_id),
    }


@router.put("/studies/{project_id}")
def update_study(project_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    _project_or_404(project_id, user)
    payload = payload or {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="A study name is required.")
    project = competitors_store.update_study(
        project_id,
        name,
        str(payload.get("status") or "active"),
        str(payload.get("description") or "").strip() or None,
    )
    if not project:
        raise HTTPException(status_code=404, detail="Study not found")
    return {"study": project}


@router.delete("/studies/{project_id}")
def remove_study(project_id: int, user: dict = Depends(require_permission("competitors.manage"))):
    _project_or_404(project_id, user)
    if not delete_project(project_id):
        raise HTTPException(status_code=500, detail="Unable to delete the study.")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Business profile
# --------------------------------------------------------------------------- #
@router.get("/studies/{project_id}/profile")
def get_profile(project_id: int, user: dict = Depends(require_permission("competitors.view"))):
    _project_or_404(project_id, user)
    return {"profile": business_profile_store.get_profile(project_id)}


@router.post("/studies/{project_id}/profile")
def build_profile(project_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    """Derive structured market context from what the user typed.

    Returns `ai_derived` alongside the profile so the UI can say whether the
    structuring step actually ran - a profile saved from raw input still works,
    but produces weaker competitor judgements, and that should be visible
    rather than inferred later from poor matches.
    """
    _project_or_404(project_id, user)
    payload = payload or {}
    if not str(payload.get("name") or "").strip():
        raise HTTPException(status_code=400, detail="A business name is required.")
    if payload.get("target_countries") is not None and not isinstance(payload["target_countries"], list):
        raise HTTPException(status_code=400, detail="target_countries must be a list of ISO country codes.")
    return business_profile_store.build_profile(project_id, payload)


@router.put("/studies/{project_id}/profile")
def update_profile(project_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    """Save user edits to the profile without re-deriving it."""
    _project_or_404(project_id, user)
    payload = payload or {}
    if payload.get("target_countries") is not None and not isinstance(payload["target_countries"], list):
        raise HTTPException(status_code=400, detail="target_countries must be a list of ISO country codes.")
    existing = business_profile_store.get_profile(project_id) or {}
    merged = {**existing, **payload}
    profile = business_profile_store.upsert_profile(project_id, merged)
    if not profile:
        raise HTTPException(status_code=400, detail="Could not save the profile.")
    return {"profile": profile}


# --------------------------------------------------------------------------- #
# Documents (offline studies) - upload, then extract text in the background.
# --------------------------------------------------------------------------- #
@router.get("/studies/{project_id}/documents")
def list_documents(project_id: int, user: dict = Depends(require_permission("competitors.view"))):
    """Poll this while any document's status is 'uploaded'/'processing' — that's
    the only progress signal extraction has, no separate run-tracking needed."""
    _project_or_404(project_id, user)
    return {"documents": competitor_documents_store.list_documents(project_id)}


@router.get("/documents/{document_id}/text")
def get_document_text(document_id: int, user: dict = Depends(require_permission("competitors.view"))):
    _document_or_404(document_id, user)
    text = competitor_documents_store.get_document_text(document_id)
    if text is None:
        raise HTTPException(status_code=404, detail="No extracted text for this document.")
    return {"text": text}


@router.get("/documents/{document_id}/chunks")
def list_document_chunks(document_id: int, user: dict = Depends(require_permission("competitors.view"))):
    """Per-page/sheet detail behind a document's rolled-up status and
    extraction_error — which part failed and why, not just that something did."""
    _document_or_404(document_id, user)
    return {"chunks": competitor_documents_store.list_chunks(document_id)}


@router.post("/studies/{project_id}/documents")
async def upload_documents(
    project_id: int,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    user: dict = Depends(require_permission("competitors.manage")),
):
    """Save uploaded documents for an offline study and queue extraction for each.

    Extraction (especially OCR on a scanned PDF) can run well past a request's
    gateway timeout, so it happens as a background task rather than inline —
    same reasoning as competitor discovery below. The response returns as soon
    as files are saved; the wizard polls GET .../documents for extraction status.
    """
    _project_or_404(project_id, user)
    if not files:
        raise HTTPException(status_code=400, detail="Choose at least one file to upload.")
    if len(files) > competitor_documents_store.MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"Upload at most {competitor_documents_store.MAX_FILES_PER_UPLOAD} files at a time.",
        )
    for upload in files:
        if not competitor_documents_store.extension_allowed(upload.filename):
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
        if len(content) > competitor_documents_store.MAX_FILE_SIZE_BYTES:
            raise HTTPException(status_code=400, detail=f"'{upload.filename}' is larger than 25 MB.")
        record = competitor_documents_store.save_document(
            project_id, filename=upload.filename, content=content, mime_type=upload.content_type
        )
        if record:
            saved.append(record)
            background_tasks.add_task(competitor_documents_store.process_document, record["id"])

    if not saved:
        raise HTTPException(status_code=500, detail="Could not save the uploaded documents.")
    return {"documents": saved}


@router.delete("/documents/{document_id}")
def remove_document(document_id: int, user: dict = Depends(require_permission("competitors.manage"))):
    _document_or_404(document_id, user)
    if not competitor_documents_store.delete_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Document articles - candidates split out of a document's extracted text,
# reviewed and approved before they become real articles.
# --------------------------------------------------------------------------- #
@router.get("/studies/{project_id}/document-articles")
def list_document_articles(project_id: int, user: dict = Depends(require_permission("competitors.view"))):
    """Poll this while any document's articles_status is 'generating' — same
    shape as list_documents for extraction, no separate run-tracking needed."""
    _project_or_404(project_id, user)
    return {"articles": competitor_document_articles.list_candidates(project_id)}


@router.post("/document-articles/{candidate_id}/status")
def set_document_article_status(
    candidate_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))
):
    """Approving materializes the candidate into a real `articles` row
    (see competitor_document_articles._materialize); rejecting just marks it."""
    status = str((payload or {}).get("status") or "").strip().lower()
    existing = competitor_document_articles.get_candidate(candidate_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Document article not found")
    ensure_project_visible(existing["project_id"], user)

    candidate = competitor_document_articles.set_status(candidate_id, status)
    if not candidate:
        raise HTTPException(status_code=400, detail="status must be pending, approved, or rejected.")
    return {"article": candidate}


@router.post("/studies/{project_id}/document-articles/approve-all")
def approve_all_document_articles(project_id: int, user: dict = Depends(require_permission("competitors.manage"))):
    _project_or_404(project_id, user)
    return {"articles": competitor_document_articles.approve_all(project_id)}


@router.post("/studies/{project_id}/analyze-documents")
def analyze_documents(project_id: int, user: dict = Depends(require_permission("competitors.analyze"))):
    """Offline studies have no competitors to name until their evidence exists.

    Names the companies the approved document articles are actually about,
    tracks them, then runs the same `generate_findings` an online study uses -
    see document_analysis.py for why that ordering has to happen here rather
    than at upload time.
    """
    _project_or_404(project_id, user)
    result = document_analysis.analyze_documents(project_id)
    if result.get("error"):
        status = 502 if result.get("error_code") else 400
        raise HTTPException(status_code=status, detail=result["error"])
    return {
        **result,
        "findings": competitor_analysis.list_findings(project_id),
    }


# --------------------------------------------------------------------------- #
# Competitors
# --------------------------------------------------------------------------- #
@router.get("/studies/{project_id}/competitors")
def list_competitors(project_id: int, user: dict = Depends(require_permission("competitors.view"))):
    _project_or_404(project_id, user)
    return {"competitors": competitors_store.competitor_overview(project_id)}


@router.post("/studies/{project_id}/competitors")
def add_competitor(project_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    _project_or_404(project_id, user)
    payload = payload or {}
    if not str(payload.get("name") or "").strip():
        raise HTTPException(status_code=400, detail="A competitor name is required.")
    record = competitors_store.upsert_competitor(
        project_id, {**payload, "discovery_source": payload.get("discovery_source") or "manual"}
    )
    if not record:
        raise HTTPException(status_code=400, detail="Could not save the competitor.")
    competitors_store.rerank_competitors(project_id)
    return {"competitor": record}


@router.post("/studies/{project_id}/competitors/import")
async def import_competitors(
    project_id: int, file: UploadFile = File(...), user: dict = Depends(require_permission("competitors.manage"))
):
    """Import competitors from the scraper app's JSONL export
    (`GET /api/competitors/export` there - see its CLAUDE.md's Handoff section).

    A competitor list the scraper already confirmed by tracking real channels
    doesn't need to be re-guessed here by document_analysis.py's LLM pass or
    re-typed by hand - this just upserts each row the same way add_competitor
    does. A study's tracked-competitor list is at most a few dozen rows, small
    enough to read and upsert inline rather than as a background job like
    document extraction below.
    """
    _project_or_404(project_id, user)
    raw = (await file.read()).decode("utf-8", errors="replace")
    if not raw.strip():
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if raw.lstrip()[:1] == "[":
        raise HTTPException(
            status_code=400, detail="Expected JSON Lines (one competitor object per line), not a JSON array."
        )

    received = saved = 0
    errors: list[str] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            if len(errors) < 50:
                errors.append(f"line {lineno}: invalid JSON")
            continue
        if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
            if len(errors) < 50:
                errors.append(f"line {lineno}: missing name")
            continue
        received += 1
        record = competitors_store.upsert_competitor(
            project_id, {**entry, "discovery_source": entry.get("discovery_source") or "scraper_import"}
        )
        if record:
            saved += 1
        elif len(errors) < 50:
            errors.append(f"line {lineno}: could not save '{entry.get('name')}'")

    if received == 0:
        raise HTTPException(status_code=400, detail="Nothing to import.")
    if saved == 0:
        raise HTTPException(status_code=400, detail=f"All {received} rows were rejected by the database.")

    competitors_store.rerank_competitors(project_id)
    return {"received": received, "saved": saved, "skipped": received - saved, "errors": errors}


@router.put("/competitors/{competitor_id}")
def update_competitor(competitor_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    competitor = _competitor_or_404(competitor_id, user)
    record = competitors_store.upsert_competitor(
        competitor["project_id"], {**competitor, **(payload or {})}
    )
    competitors_store.rerank_competitors(competitor["project_id"])
    return {"competitor": record}


@router.post("/competitors/{competitor_id}/status")
def set_status(competitor_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    """Track or ignore a competitor.

    Only tracked competitors get a finding: analysis is one LLM call each, and
    a study named from documents can surface companies that are mentioned but
    are not who the user is watching.
    """
    _competitor_or_404(competitor_id, user)
    status = str((payload or {}).get("status") or "").strip().lower()
    record = competitors_store.set_competitor_status(competitor_id, status)
    if not record:
        raise HTTPException(status_code=400, detail="status must be suggested, tracked, or ignored.")
    return {"competitor": record}


@router.delete("/competitors/{competitor_id}")
def remove_competitor(competitor_id: int, user: dict = Depends(require_permission("competitors.manage"))):
    competitor = _competitor_or_404(competitor_id, user)
    competitors_store.delete_competitor(competitor_id)
    competitors_store.rerank_competitors(competitor["project_id"])
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
ANALYSIS_SCOPES = {"pending", "all", "selected"}


@router.get("/studies/{project_id}/analysis-scope")
def analysis_scope(project_id: int, user: dict = Depends(require_permission("competitors.view"))):
    """This study's documents annotated with approved-article counts and
    whether a completed run already analyzed each - what the run-analysis
    dialog renders its scope choices (and the hand-pick checklist) from."""
    _project_or_404(project_id, user)
    return {"documents": analysis_runs_store.documents_with_scope(project_id)}


@router.get("/studies/{project_id}/analysis-runs")
def list_analysis_runs(project_id: int, user: dict = Depends(require_permission("competitors.view"))):
    """This study's analysis-run history, newest first - the "Analysis run"
    filter's source, and what "Analysis #N" is numbered from."""
    _project_or_404(project_id, user)
    return {"runs": analysis_runs_store.list_runs(project_id)}


@router.post("/studies/{project_id}/analyze")
def analyze(
    project_id: int,
    background_tasks: BackgroundTasks,
    payload: dict = None,
    user: dict = Depends(require_permission("competitors.analyze")),
):
    """Queue analysis as a background job and return immediately.

    Analysis reads evidence that is already stored - the articles this study's
    uploaded documents were split into - so there is nothing to gather first.
    `scope` picks which documents' evidence this run draws from: 'pending'
    (documents no completed run has analyzed yet, the default), 'all', or
    'selected' (an explicit `document_ids` list from the dialog's checklist).

    One LLM call per competitor runs for minutes, which used to be minutes of
    an open request showing an undifferentiated spinner. The checks that can
    fail immediately stay here so they still answer with a real status code;
    everything slow moves into the job, and the UI polls
    GET .../analyze/{run_id} for live progress.
    """
    _project_or_404(project_id, user)
    payload = payload or {}
    scope = str(payload.get("scope") or "pending").strip().lower()
    if scope not in ANALYSIS_SCOPES:
        raise HTTPException(status_code=400, detail="scope must be pending, all, or selected.")
    document_ids = payload.get("document_ids") if scope == "selected" else None
    if scope == "selected" and not document_ids:
        raise HTTPException(status_code=400, detail="Select at least one document.")

    if not project_has_articles(project_id):
        raise HTTPException(
            status_code=400,
            detail="No evidence yet. Upload documents and approve their articles before running analysis.",
        )

    # Double-clicking "Run analysis" attaches to the run already in flight
    # rather than starting a second one against the same competitors.
    active = analysis_runs_store.get_active_run(project_id)
    if active:
        return {"run_id": active["id"], "status": active["status"]}

    run = analysis_runs_store.create_run(project_id, scope)
    background_tasks.add_task(
        competitor_analysis.run_analysis_job, run["id"], project_id, scope, document_ids,
    )
    return {"run_id": run["id"], "sequence_number": run["sequence_number"], "status": "queued"}


@router.get("/studies/{project_id}/analyze/{run_id}")
def analyze_status(project_id: int, run_id: int, user: dict = Depends(require_permission("competitors.view"))):
    """Progress for one analysis job, including its live `logs`.

    Findings are returned on the terminal poll so the workspace can render the
    new cards without a second round trip, matching what the old synchronous
    endpoint handed back.
    """
    _project_or_404(project_id, user)
    run = analysis_runs_store.get_run(run_id)
    if not run or run["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    if run["status"] in ("success", "failed"):
        run = {**run, "findings": competitor_analysis.list_findings(project_id)}
    return {"run": run}


@router.get("/studies/{project_id}/findings")
def list_findings(project_id: int, impact: str | None = None, competitor_id: int | None = None,
                  history: bool = False, search: str | None = None,
                  date_from: str | None = None, date_to: str | None = None,
                  pipeline_run_id: str | None = None, analysis_run_id: int | None = None,
                  user: dict = Depends(require_permission("competitors.view"))):
    _project_or_404(project_id, user)
    return {
        "findings": competitor_analysis.list_findings(
            project_id, competitor_id=competitor_id, impact_level=impact, latest_only=not history,
            search=search, date_from=date_from, date_to=date_to, pipeline_run_id=pipeline_run_id,
            analysis_run_id=analysis_run_id,
        )
    }


@router.get("/findings/{finding_id}")
def get_finding(finding_id: int, user: dict = Depends(require_permission("competitors.view"))):
    """One finding as a full report, including the evidence it was filtered from."""
    finding = competitor_analysis.get_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    ensure_project_visible(finding["project_id"], user)
    return {
        "finding": finding,
        "rejected_evidence": competitor_analysis.rejected_evidence(finding["competitor_id"]),
        "history": competitor_analysis.list_findings(
            finding["project_id"], competitor_id=finding["competitor_id"], latest_only=False,
        ),
    }


@router.post("/findings/{finding_id}/validate")
def validate_finding(finding_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    existing = competitor_analysis.get_finding(finding_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Finding not found")
    ensure_project_visible(existing["project_id"], user)

    status = str((payload or {}).get("status") or "").strip().lower()
    finding = competitor_analysis.set_finding_validation(
        finding_id, status, str((payload or {}).get("notes") or "")
    )
    if not finding:
        raise HTTPException(status_code=400, detail="status must be pending, validated, or rejected.")
    return {"finding": finding}
