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


from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from services.competitors import business_profile_store
from services.competitors import competitor_analysis
from services.competitors import competitor_document_articles
from services.competitors import competitor_documents_store
from services.competitors import competitors_store
from services.competitors import document_analysis
from services.competitors.countries import validate_countries
from psycopg.types.json import Jsonb
import db
from services.auth.auth import require_permission
from services.pipeline.pipeline_runs import get_pipeline_run
from services.projects.projects_store import delete_project, project_has_articles

router = APIRouter(prefix="/api/competitor", tags=["competitor"])


def _project_or_404(project_id: int) -> dict:
    project = db.fetch_one(
        "select id, name, mode, status, last_run_at, last_run_status from projects where id = %s",
        (int(project_id),),
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _competitor_or_404(competitor_id: int) -> dict:
    competitor = competitors_store.get_competitor(competitor_id)
    if not competitor:
        raise HTTPException(status_code=404, detail="Competitor not found")
    return competitor


# --------------------------------------------------------------------------- #
# Studies
# --------------------------------------------------------------------------- #
@router.get("/studies")
def list_studies(user: dict = Depends(require_permission("competitors.view"))):
    """Competitor-mode projects with enough summary to render the index."""
    return {
        "studies": db.fetch_all(
            """
            with latest_findings as (
                -- One row per competitor's *current* card, not per generation
                -- event: generate_finding() always inserts (never updates), so
                -- re-running analysis on the same competitor leaves its older
                -- findings in place as history rather than superseding them in
                -- place. Counting competitor_findings directly counted every
                -- one of those, so the number grew on every re-run even with
                -- the competitor set unchanged, and didn't match the study's
                -- own findings grid - which shows one card per competitor, the
                -- newest, excluding rejected ones.
                select distinct on (competitor_id)
                       project_id, competitor_id, impact_level, generated_at
                from competitor_findings
                where validation_status != 'rejected'
                order by competitor_id, generated_at desc
            )
            select p.id, p.name, p.status, p.mode, p.created_at, p.updated_at,
                   p.last_run_at, p.last_run_status,
                   bp.name as business_name, bp.website as business_website,
                   bp.market, bp.industry,
                   coalesce(c.tracked, 0)::int   as tracked_competitors,
                   coalesce(c.suggested, 0)::int as suggested_competitors,
                   coalesce(f.total, 0)::int     as finding_count,
                   coalesce(f.high, 0)::int      as high_impact_count,
                   f.latest_generated_at
            from projects p
            left join business_profiles bp on bp.project_id = p.id
            left join (
                select project_id,
                       count(*) filter (where status = 'tracked')   as tracked,
                       count(*) filter (where status = 'suggested') as suggested
                from competitors group by project_id
            ) c on c.project_id = p.id
            left join (
                select project_id, count(*) as total,
                       count(*) filter (where impact_level = 'high') as high,
                       max(generated_at) as latest_generated_at
                from latest_findings group by project_id
            ) f on f.project_id = p.id
            where p.mode = 'competitor'
            order by p.created_at desc
            """
        )
    }


@router.get("/studies/{project_id}/findings/recent")
def list_recent_study_findings(
    project_id: int,
    limit: int = 10,
    offset: int = 0,
    user: dict = Depends(require_permission("competitors.view")),
):
    """Paginated findings for one study, highest impact first — powers the Dashboard/Reports pulse card."""
    _project_or_404(project_id)
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
    project = db.fetch_one(
        """
        insert into projects (name, mode, status, description)
        values (%s, 'competitor', %s, %s)
        returning id, name, mode, status, created_at
        """,
        (name, str((payload or {}).get("status") or "active"),
         str((payload or {}).get("description") or "").strip() or None),
    )
    if not project:
        raise HTTPException(status_code=500, detail="Could not create the study.")
    return {"study": project}


@router.get("/studies/{project_id}")
def get_study(project_id: int, user: dict = Depends(require_permission("competitors.view"))):
    project = _project_or_404(project_id)
    return {
        "study": project,
        "profile": business_profile_store.get_profile(project_id),
        "competitors": competitors_store.competitor_overview(project_id),
        "findings": competitor_analysis.list_findings(project_id),
    }


@router.put("/studies/{project_id}")
def update_study(project_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    _project_or_404(project_id)
    payload = payload or {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="A study name is required.")
    project = db.fetch_one(
        """
        update projects
           set name = %s, status = %s, description = %s, updated_at = now()
         where id = %s and mode = 'competitor'
        returning id, name, mode, status, description, created_at, updated_at
        """,
        (name, str(payload.get("status") or "active"),
         str(payload.get("description") or "").strip() or None, int(project_id)),
    )
    if not project:
        raise HTTPException(status_code=404, detail="Study not found")
    return {"study": project}


@router.delete("/studies/{project_id}")
def remove_study(project_id: int, user: dict = Depends(require_permission("competitors.manage"))):
    _project_or_404(project_id)
    if not delete_project(project_id):
        raise HTTPException(status_code=500, detail="Unable to delete the study.")
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Business profile
# --------------------------------------------------------------------------- #
@router.get("/studies/{project_id}/profile")
def get_profile(project_id: int, user: dict = Depends(require_permission("competitors.view"))):
    _project_or_404(project_id)
    return {"profile": business_profile_store.get_profile(project_id)}


@router.post("/studies/{project_id}/profile")
def build_profile(project_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    """Derive structured market context from what the user typed.

    Returns `ai_derived` alongside the profile so the UI can say whether the
    structuring step actually ran - a profile saved from raw input still works,
    but produces weaker competitor judgements, and that should be visible
    rather than inferred later from poor matches.
    """
    _project_or_404(project_id)
    payload = payload or {}
    if not str(payload.get("name") or "").strip():
        raise HTTPException(status_code=400, detail="A business name is required.")
    if payload.get("target_countries") is not None and not isinstance(payload["target_countries"], list):
        raise HTTPException(status_code=400, detail="target_countries must be a list of ISO country codes.")
    return business_profile_store.build_profile(project_id, payload)


@router.put("/studies/{project_id}/profile")
def update_profile(project_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    """Save user edits to the profile without re-deriving it."""
    _project_or_404(project_id)
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
    _project_or_404(project_id)
    return {"documents": competitor_documents_store.list_documents(project_id)}


@router.get("/documents/{document_id}/text")
def get_document_text(document_id: int, user: dict = Depends(require_permission("competitors.view"))):
    text = competitor_documents_store.get_document_text(document_id)
    if text is None:
        raise HTTPException(status_code=404, detail="No extracted text for this document.")
    return {"text": text}


@router.get("/documents/{document_id}/chunks")
def list_document_chunks(document_id: int, user: dict = Depends(require_permission("competitors.view"))):
    """Per-page/sheet detail behind a document's rolled-up status and
    extraction_error — which part failed and why, not just that something did."""
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
    _project_or_404(project_id)
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
    _project_or_404(project_id)
    return {"articles": competitor_document_articles.list_candidates(project_id)}


@router.post("/document-articles/{candidate_id}/status")
def set_document_article_status(
    candidate_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))
):
    """Approving materializes the candidate into a real `articles` row
    (see competitor_document_articles._materialize); rejecting just marks it."""
    status = str((payload or {}).get("status") or "").strip().lower()
    candidate = competitor_document_articles.set_status(candidate_id, status)
    if not candidate:
        raise HTTPException(status_code=400, detail="status must be pending, approved, or rejected.")
    return {"article": candidate}


@router.post("/studies/{project_id}/document-articles/approve-all")
def approve_all_document_articles(project_id: int, user: dict = Depends(require_permission("competitors.manage"))):
    _project_or_404(project_id)
    return {"articles": competitor_document_articles.approve_all(project_id)}


@router.post("/studies/{project_id}/analyze-documents")
def analyze_documents(project_id: int, user: dict = Depends(require_permission("competitors.analyze"))):
    """Offline studies have no competitors to name until their evidence exists.

    Names the companies the approved document articles are actually about,
    tracks them, then runs the same `generate_findings` an online study uses -
    see document_analysis.py for why that ordering has to happen here rather
    than at upload time.
    """
    _project_or_404(project_id)
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
    _project_or_404(project_id)
    return {"competitors": competitors_store.competitor_overview(project_id)}


@router.post("/studies/{project_id}/competitors")
def add_competitor(project_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    _project_or_404(project_id)
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


@router.put("/competitors/{competitor_id}")
def update_competitor(competitor_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    competitor = _competitor_or_404(competitor_id)
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
    _competitor_or_404(competitor_id)
    status = str((payload or {}).get("status") or "").strip().lower()
    record = competitors_store.set_competitor_status(competitor_id, status)
    if not record:
        raise HTTPException(status_code=400, detail="status must be suggested, tracked, or ignored.")
    return {"competitor": record}


@router.delete("/competitors/{competitor_id}")
def remove_competitor(competitor_id: int, user: dict = Depends(require_permission("competitors.manage"))):
    competitor = _competitor_or_404(competitor_id)
    competitors_store.delete_competitor(competitor_id)
    competitors_store.rerank_competitors(competitor["project_id"])
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
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

    `pipeline_run_id`, when given, scopes evidence to one completed analysis
    run instead of the `period_days` date window: the "Analysis run" tab in the
    dialog, matching the same choice Reports offers.

    One LLM call per competitor runs for minutes, which used to be minutes of
    an open request showing an undifferentiated spinner. The checks that can
    fail immediately stay here so they still answer with a real status code;
    everything slow moves into the job, and the UI polls
    GET .../analyze/{run_id} for live progress.
    """
    _project_or_404(project_id)
    payload = payload or {}
    period_days = max(1, min(int(payload.get("period_days") or competitor_analysis.DEFAULT_PERIOD_DAYS), 365))
    pipeline_run_id = payload.get("pipeline_run_id") or None
    if pipeline_run_id is not None:
        run = get_pipeline_run(pipeline_run_id)
        if not run or int(run.get("project_id") or 0) != int(project_id):
            raise HTTPException(status_code=404, detail="Analysis run not found for this study.")

    if not project_has_articles(project_id):
        raise HTTPException(
            status_code=400,
            detail="No evidence yet. Upload documents and approve their articles before running analysis.",
        )

    # Double-clicking "Run analysis" attaches to the run already in flight
    # rather than starting a second one against the same competitors.
    active = competitor_analysis.get_active_analysis_run(project_id)
    if active:
        return {"run_id": active["run_id"], "status": active["status"]}

    run_id = competitor_analysis.create_analysis_run(project_id)
    background_tasks.add_task(
        competitor_analysis.run_analysis_job, run_id, project_id, period_days, pipeline_run_id,
    )
    return {"run_id": run_id, "status": "queued"}


@router.get("/studies/{project_id}/analyze/{run_id}")
def analyze_status(project_id: int, run_id: str, user: dict = Depends(require_permission("competitors.view"))):
    """Progress for one analysis job, including its live `logs`.

    Findings are returned on the terminal poll so the workspace can render the
    new cards without a second round trip, matching what the old synchronous
    endpoint handed back.
    """
    _project_or_404(project_id)
    run = competitor_analysis.get_analysis_run(run_id)
    if not run or run["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Analysis run not found.")
    if run["status"] in ("success", "failed"):
        run = {**run, "findings": competitor_analysis.list_findings(project_id)}
    return {"run": run}


@router.get("/studies/{project_id}/findings")
def list_findings(project_id: int, impact: str | None = None, competitor_id: int | None = None,
                  history: bool = False, search: str | None = None,
                  date_from: str | None = None, date_to: str | None = None,
                  pipeline_run_id: str | None = None,
                  user: dict = Depends(require_permission("competitors.view"))):
    _project_or_404(project_id)
    return {
        "findings": competitor_analysis.list_findings(
            project_id, competitor_id=competitor_id, impact_level=impact, latest_only=not history,
            search=search, date_from=date_from, date_to=date_to, pipeline_run_id=pipeline_run_id,
        )
    }


@router.get("/findings/{finding_id}")
def get_finding(finding_id: int, user: dict = Depends(require_permission("competitors.view"))):
    """One finding as a full report, including the evidence it was filtered from."""
    finding = competitor_analysis.get_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    return {
        "finding": finding,
        "rejected_evidence": competitor_analysis.rejected_evidence(finding["competitor_id"]),
        "history": competitor_analysis.list_findings(
            finding["project_id"], competitor_id=finding["competitor_id"], latest_only=False,
        ),
    }


@router.post("/findings/{finding_id}/validate")
def validate_finding(finding_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    status = str((payload or {}).get("status") or "").strip().lower()
    finding = competitor_analysis.set_finding_validation(
        finding_id, status, str((payload or {}).get("notes") or "")
    )
    if not finding:
        raise HTTPException(status_code=400, detail="status must be pending, validated, or rejected.")
    return {"finding": finding}
