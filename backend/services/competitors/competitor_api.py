"""HTTP surface for the competitor study.

Kept in its own APIRouter rather than appended to main.py: this is a separate
experience from sentiment/opinions, and separating the routes is what keeps the
two from tangling as either one grows.

Long-running work (website scrape, analysis generation) runs synchronously and
is expected to take tens of seconds — the UI shows staged progress for it,
matching how the existing project discovery flow behaves. Competitor discovery
is the exception: it runs as a background job (see discover()/discover_status()
below) because it can take minutes once web corroboration and per-competitor
account lookups are added up, well past any gateway timeout.
"""

from __future__ import annotations


from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from services.competitors import business_profile_store
from services.competitors import competitor_analysis
from services.competitors import competitor_discovery
from services.competitors import competitor_document_articles
from services.competitors import competitor_documents_store
from services.competitors import competitors_store
from services.competitors import document_analysis
from services.competitors.countries import validate_countries
from services.projects.projects_store import REPEAT_WEEKDAYS
from psycopg.types.json import Jsonb
import db
from services.auth.auth import require_permission
from services.pipeline.pipeline_runs import get_active_run_for_project, get_pipeline_run
from services.projects.projects_store import delete_project, list_sources_for_project, project_has_articles

router = APIRouter(prefix="/api/competitor", tags=["competitor"])


def _project_or_404(project_id: int) -> dict:
    project = db.fetch_one(
        "select id, name, mode, status, repeat_enabled, next_run_at, last_run_at, last_run_status "
        "from projects where id = %s",
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
                   p.repeat_enabled, p.next_run_at, p.last_run_at, p.last_run_status,
                   bp.name as business_name, bp.website as business_website,
                   bp.market, bp.industry, bp.scrape_status,
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
    """Scrape the business's website and derive its market context.

    Returns the scrape outcome alongside the profile so the UI can say how many
    pages were actually read — a thin scrape produces a weak profile, and that
    should be visible rather than inferred later from poor competitor matches.
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
    """Save user edits to the profile without re-scraping or re-deriving."""
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
                    "(pdf, doc, docx, xls, xlsx, csv, png, jpg, jpeg)."
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
# Discovery
# --------------------------------------------------------------------------- #
@router.post("/studies/{project_id}/discover")
def discover(
    project_id: int,
    background_tasks: BackgroundTasks,
    payload: dict = None,
    user: dict = Depends(require_permission("competitors.analyze")),
):
    """Queue competitor discovery as a background job and return immediately.

    Discovery chains an LLM call, live web corroboration per candidate, and
    (with_accounts) a further LLM call per competitor - easily minutes end to
    end, which running inline used to push past the gateway timeout and 504.
    The UI polls GET .../discover/{run_id} for progress and refetches
    competitors once the run succeeds.
    """
    _project_or_404(project_id)
    profile = business_profile_store.get_profile(project_id)
    if not profile:
        raise HTTPException(status_code=400, detail="Add the business profile before discovering competitors.")

    payload = payload or {}
    limit = max(3, min(int(payload.get("limit") or competitor_discovery.MAX_COMPETITORS), 20))
    with_accounts = bool(payload.get("with_accounts"))

    active = competitor_discovery.get_active_discovery_run(project_id)
    if active:
        return {"run_id": active["run_id"], "status": active["status"]}

    run_id = competitor_discovery.create_discovery_run(project_id)
    background_tasks.add_task(
        competitor_discovery.run_discovery_job, run_id, project_id, profile, limit, with_accounts
    )
    return {"run_id": run_id, "status": "queued", "model": competitor_discovery.discovery_model()}


@router.get("/studies/{project_id}/discover/{run_id}")
def discover_status(project_id: int, run_id: str, user: dict = Depends(require_permission("competitors.view"))):
    _project_or_404(project_id)
    run = competitor_discovery.get_discovery_run(run_id)
    if not run or run["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Discovery run not found.")
    return {"run": run}


@router.post("/studies/{project_id}/discover-accounts")
def discover_accounts_bulk(
    project_id: int,
    background_tasks: BackgroundTasks,
    user: dict = Depends(require_permission("competitors.analyze")),
):
    """Phase 3: find channels for every tracked competitor that doesn't have one yet.

    Deliberately separate from discover() (Phase 1, finding the competitors
    themselves) so channel discovery only spends LLM calls on companies the user
    actually chose to track, not every AI suggestion.
    """
    _project_or_404(project_id)
    targets = [
        {"id": c["id"], "name": c["name"], "website": c.get("website")}
        for c in competitors_store.competitor_overview(project_id)
        if c["status"] == "tracked" and not c.get("account_count")
    ]
    if not targets:
        return {"run_id": None, "status": "success", "message": "No tracked competitors need channels."}

    active = competitor_discovery.get_active_discovery_run(project_id)
    if active:
        return {"run_id": active["run_id"], "status": active["status"]}

    run_id = competitor_discovery.create_discovery_run(project_id)
    background_tasks.add_task(competitor_discovery.run_accounts_discovery_job, run_id, project_id, targets)
    return {"run_id": run_id, "status": "queued"}


@router.post("/competitors/{competitor_id}/accounts/discover")
def discover_competitor_accounts(competitor_id: int, user: dict = Depends(require_permission("competitors.analyze"))):
    competitor = _competitor_or_404(competitor_id)
    profile = business_profile_store.get_profile(competitor["project_id"]) or {}
    target_countries = validate_countries(profile.get("target_countries"))
    found = competitor_discovery.discover_accounts(competitor["name"], competitor.get("website"), target_countries)
    for account in found:
        competitors_store.upsert_account(competitor_id, account)
    return {"accounts": competitors_store.list_accounts(competitor_id)}


# --------------------------------------------------------------------------- #
# Competitors + accounts
# --------------------------------------------------------------------------- #
@router.get("/studies/{project_id}/competitors")
def list_competitors(project_id: int, user: dict = Depends(require_permission("competitors.view"))):
    _project_or_404(project_id)
    competitors = competitors_store.competitor_overview(project_id)
    for competitor in competitors:
        competitor["accounts"] = competitors_store.list_accounts(competitor["id"])
    return {"competitors": competitors}


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


@router.post("/studies/{project_id}/competitors/manual")
def add_competitor_manual(project_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    """Create (or merge into) a competitor and validate its sources immediately.

    Manual sources skip the pending/confirm step AI-discovered accounts need:
    the user typed the URL themselves, so there is no attribution risk to guard
    against. Every source is validated before anything is written, so a bad
    URL fails the whole request rather than leaving a half-created competitor.
    """
    _project_or_404(project_id)
    payload = payload or {}
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="A competitor name is required.")

    raw_sources = payload.get("sources") or []
    if not isinstance(raw_sources, list):
        raise HTTPException(status_code=400, detail="sources must be a list.")

    normalized_sources = []
    for index, source in enumerate(raw_sources, start=1):
        source = source or {}
        platform = str(source.get("platform") or "").strip().lower()
        if platform not in competitors_store.PLATFORM_SOURCE_TYPE:
            raise HTTPException(status_code=400, detail=f"Source {index}: unsupported source type '{platform}'.")
        handle_input = str(source.get("handle") or "").strip().lstrip("@")
        url = competitors_store.resolve_account_url(platform, source.get("url"), handle_input)
        if not url:
            raise HTTPException(status_code=400, detail=f"Source {index}: enter a valid value.")
        normalized_sources.append({
            "platform": platform,
            "url": url,
            "handle": handle_input or None,
        })

    competitor = competitors_store.upsert_competitor(
        project_id, {**payload, "status": "tracked", "discovery_source": "manual"}
    )
    if not competitor:
        raise HTTPException(status_code=400, detail="Could not save the competitor.")

    accounts = []
    for source in normalized_sources:
        account = competitors_store.upsert_account(
            competitor["id"], {**source, "validation_status": "valid", "confidence": 1.0}
        )
        if account:
            accounts.append(account)

    competitors_store.rerank_competitors(project_id)
    return {"competitor": competitor, "accounts": accounts}


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
    """Track or ignore a competitor. Tracking links its valid accounts as sources.

    Phase 2: the first time an AI-suggested competitor is tracked, corroborate
    it against the live web here — the check discover() skips on every
    candidate up front now runs once, only on the one the user actually chose.
    Never blocks the track itself; a company that fails to corroborate still
    gets tracked, just flagged, since the user has already decided to track it.
    """
    competitor = _competitor_or_404(competitor_id)
    status = str((payload or {}).get("status") or "").strip().lower()
    record = competitors_store.set_competitor_status(competitor_id, status)
    if not record:
        raise HTTPException(status_code=400, detail="status must be suggested, tracked, or ignored.")

    verification = None
    signals = record.get("size_signals") or {}
    if status == "tracked" and record.get("discovery_source") == "ai" and not signals.get("checked_live"):
        verification = competitor_discovery.verify_competitor(record["name"], record.get("website"))
        record = competitors_store.upsert_competitor(competitor["project_id"], {
            **record,
            "website": verification["resolved_website"] or record.get("website"),
            "size_signals": {
                **signals,
                "checked_live": True,
                "site_reachable": verification["reachable"],
                "search_hits": verification["search_hits"],
            },
        }) or record

    sync = competitors_store.sync_project_sources(competitor["project_id"])
    return {"competitor": record, "sources": sync, "verification": verification}


@router.delete("/competitors/{competitor_id}")
def remove_competitor(competitor_id: int, user: dict = Depends(require_permission("competitors.manage"))):
    competitor = _competitor_or_404(competitor_id)
    competitors_store.delete_competitor(competitor_id)
    competitors_store.rerank_competitors(competitor["project_id"])
    return {"ok": True}


@router.get("/competitors/{competitor_id}/accounts")
def list_accounts(competitor_id: int, user: dict = Depends(require_permission("competitors.view"))):
    _competitor_or_404(competitor_id)
    return {"accounts": competitors_store.list_accounts(competitor_id)}


@router.post("/competitors/{competitor_id}/accounts")
def add_account(competitor_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    _competitor_or_404(competitor_id)
    account = competitors_store.upsert_account(competitor_id, payload or {})
    if not account:
        raise HTTPException(status_code=400, detail="platform and url are required.")
    return {"account": account}


@router.post("/accounts/{account_id}/validate")
def validate_account(account_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    """Accept or reject a discovered account.

    Accepting registers it as a scrape source; rejecting detaches it. Nothing is
    scraped on a guess, because a misattributed account puts another company's
    activity into a report someone plans against.
    """
    status = str((payload or {}).get("status") or "").strip().lower()
    account = competitors_store.set_account_validation(
        account_id, status, str((payload or {}).get("reason") or "")
    )
    if not account:
        raise HTTPException(status_code=400, detail="status must be pending, valid, or rejected.")
    return {"account": account}


@router.delete("/accounts/{account_id}")
def remove_account(account_id: int, user: dict = Depends(require_permission("competitors.manage"))):
    competitors_store.delete_account(account_id)
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

    `scrape` in the payload is the user's explicit choice from the "Run
    analysis" dialog: True scrapes+enriches first regardless of what's already
    there, False skips straight to analysis on whatever evidence already
    exists. Omitting it falls back to the old auto-detect behaviour (scrape
    only when the project has zero articles) for any caller that predates the
    dialog, e.g. a scheduled run.

    `pipeline_run_id`, when given, scopes evidence to one already-completed
    scrape run instead of the `period_days` date window - the "Pipeline run"
    tab in the dialog, matching the same choice Reports offers. It always
    implies skipping a fresh scrape: the point of picking a specific past run
    is to look at exactly what it gathered, and a new scrape wouldn't add
    anything to that run's articles.

    One LLM call per competitor - preceded, when scraping, by a full crawl of
    every source in the study - runs for minutes, which used to be minutes of
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
            raise HTTPException(status_code=404, detail="Pipeline run not found for this study.")
    scrape_choice = payload.get("scrape")
    needs_scrape = (
        False if pipeline_run_id
        else scrape_choice if isinstance(scrape_choice, bool)
        else not project_has_articles(project_id)
    )

    if needs_scrape:
        if get_active_run_for_project(project_id):
            raise HTTPException(
                status_code=409,
                detail="A scrape is already running for this study. Try again once it finishes.",
            )
        if not list_sources_for_project(project_id):
            raise HTTPException(
                status_code=400,
                detail="No sources to scrape yet. Confirm at least one competitor channel before running analysis.",
            )

    # Double-clicking "Run analysis" attaches to the run already in flight
    # rather than starting a second one against the same competitors.
    active = competitor_analysis.get_active_analysis_run(project_id)
    if active:
        return {"run_id": active["run_id"], "status": active["status"]}

    run_id = competitor_analysis.create_analysis_run(project_id)
    background_tasks.add_task(
        competitor_analysis.run_analysis_job, run_id, project_id, period_days,
        bool(needs_scrape), pipeline_run_id,
    )
    return {"run_id": run_id, "status": "queued", "scraping": bool(needs_scrape)}


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
                  user: dict = Depends(require_permission("competitors.view"))):
    _project_or_404(project_id)
    return {
        "findings": competitor_analysis.list_findings(
            project_id, competitor_id=competitor_id, impact_level=impact, latest_only=not history,
            search=search, date_from=date_from, date_to=date_to,
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
        "accounts": competitors_store.list_accounts(finding["competitor_id"]),
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


# --------------------------------------------------------------------------- #
# Scheduling — reuses the existing project scheduler, no new machinery
# --------------------------------------------------------------------------- #
@router.get("/studies/{project_id}/schedule")
def get_schedule(project_id: int, user: dict = Depends(require_permission("competitors.view"))):
    return {"schedule": db.fetch_one(
        """
        select repeat_enabled, repeat_interval_value, repeat_interval_unit,
               repeat_weekdays, first_run_at, next_run_at, last_run_at, last_run_status,
               start_date, end_date
        from projects where id = %s
        """,
        (int(project_id),),
    )}


@router.put("/studies/{project_id}/schedule")
def set_schedule(project_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    """Enable recurring competitor scrapes via the existing project scheduler.

    Also carries the data retrieval window (start_date/end_date) - the same
    columns Opinion Monitor projects use to scope which article publish dates
    get pulled in. The dashboard keeps this window's span in sync with the
    repeat interval; the backend just persists whatever it's given.
    """
    _project_or_404(project_id)
    payload = payload or {}
    enabled = bool(payload.get("repeat_enabled"))
    unit = str(payload.get("repeat_interval_unit") or "days").strip().lower()
    if unit not in {"minutes", "hours", "days"}:
        raise HTTPException(status_code=400, detail="repeat_interval_unit must be minutes, hours, or days.")
    try:
        value = max(1, int(payload.get("repeat_interval_value") or 1))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="repeat_interval_value must be a positive number.")

    first_run = payload.get("first_run_at") or None
    start_date = str(payload.get("start_date") or "").strip() or None
    end_date = str(payload.get("end_date") or "").strip() or None

    # Only touch weekdays when the caller actually sent the field - the
    # workspace's simpler reschedule call doesn't, and a bare interval change
    # there must not silently clear a day restriction set during onboarding.
    weekdays_param = None
    if "repeat_weekdays" in payload:
        seen = set()
        weekdays = []
        for day in payload.get("repeat_weekdays") or []:
            text = str(day or "").strip().lower()
            if text and text in REPEAT_WEEKDAYS and text not in seen:
                seen.add(text)
                weekdays.append(text)
        weekdays_param = Jsonb(weekdays)

    schedule = db.fetch_one(
        """
        update projects
           set repeat_enabled = %s,
               repeat_interval_value = %s,
               repeat_interval_unit = %s,
               first_run_at = coalesce(%s::timestamptz, first_run_at),
               next_run_at = case
                   when %s then coalesce(%s::timestamptz, next_run_at, now())
                   else null
               end,
               start_date = coalesce(%s::date, start_date),
               end_date = coalesce(%s::date, end_date),
               repeat_weekdays = coalesce(%s::jsonb, repeat_weekdays)
         where id = %s
        returning repeat_enabled, repeat_interval_value, repeat_interval_unit,
                  repeat_weekdays, first_run_at, next_run_at, last_run_at, last_run_status,
                  start_date, end_date
        """,
        (enabled, value, unit, first_run, enabled, first_run, start_date, end_date, weekdays_param, int(project_id)),
    )
    return {"schedule": schedule}


@router.post("/studies/{project_id}/sync-sources")
def sync_sources(project_id: int, user: dict = Depends(require_permission("competitors.manage"))):
    """Reconcile project sources with the currently-valid competitor accounts."""
    _project_or_404(project_id)
    return {"sources": competitors_store.sync_project_sources(project_id)}
