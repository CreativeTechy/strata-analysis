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

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from services.competitors import business_profile_store
from services.competitors import competitor_analysis
from services.competitors import competitor_discovery
from services.competitors import competitors_store
import db
from services.auth.auth import require_permission
from services.pipeline.pipeline import run_scraper_pipeline
from services.pipeline.pipeline_runs import create_pipeline_run, get_active_run_for_project, get_pipeline_run
from services.projects.projects_store import list_sources_for_project, project_has_articles

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
                from competitor_findings group by project_id
            ) f on f.project_id = p.id
            where p.mode = 'competitor'
            order by p.created_at desc
            """
        )
    }


@router.get("/overview")
def overview(user: dict = Depends(require_permission("competitors.view"))):
    """Cross-study summary for the Dashboard/Reports pulse card: totals plus recent findings."""
    totals = db.fetch_one(
        """
        select count(distinct p.id)::int as studies,
               count(distinct c.id) filter (where c.status = 'tracked')::int as tracked_competitors,
               count(distinct f.id) filter (where f.impact_level = 'high')::int as high_impact_findings
        from projects p
        left join competitors c on c.project_id = p.id
        left join competitor_findings f on f.project_id = p.id
        where p.mode = 'competitor'
        """
    ) or {"studies": 0, "tracked_competitors": 0, "high_impact_findings": 0}
    return {
        "totals": totals,
        "recent_findings": competitor_analysis.list_recent_findings(limit=6),
    }


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
    return business_profile_store.build_profile(project_id, payload)


@router.put("/studies/{project_id}/profile")
def update_profile(project_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    """Save user edits to the profile without re-scraping or re-deriving."""
    _project_or_404(project_id)
    existing = business_profile_store.get_profile(project_id) or {}
    merged = {**existing, **(payload or {})}
    profile = business_profile_store.upsert_profile(project_id, merged)
    if not profile:
        raise HTTPException(status_code=400, detail="Could not save the profile.")
    return {"profile": profile}


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
    with_accounts = payload.get("with_accounts", True) is not False

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


@router.post("/competitors/{competitor_id}/accounts/discover")
def discover_competitor_accounts(competitor_id: int, user: dict = Depends(require_permission("competitors.analyze"))):
    competitor = _competitor_or_404(competitor_id)
    found = competitor_discovery.discover_accounts(competitor["name"], competitor.get("website"))
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
    """Track or ignore a competitor. Tracking links its valid accounts as sources."""
    competitor = _competitor_or_404(competitor_id)
    status = str((payload or {}).get("status") or "").strip().lower()
    record = competitors_store.set_competitor_status(competitor_id, status)
    if not record:
        raise HTTPException(status_code=400, detail="status must be suggested, tracked, or ignored.")
    sync = competitors_store.sync_project_sources(competitor["project_id"])
    return {"competitor": record, "sources": sync}


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
def _ensure_articles(project_id: int) -> dict:
    """Run the shared scrape/enrich pipeline synchronously when a study has no
    articles yet, so analysis always has evidence to read instead of quietly
    generating zero findings.

    Reuses the exact machinery behind POST /scrape - same pipeline_runs
    tracking, same run_scraper_pipeline - rather than a second scraping path.
    Blocks the request (matching how profile scraping and analysis generation
    already run synchronously here) so `generate_findings` never runs against
    an empty project. A run already active for this project is treated as a
    conflict rather than started twice, so double-clicking "Run analysis"
    cannot kick off two scrapes.
    """
    active = get_active_run_for_project(project_id)
    if active:
        raise HTTPException(
            status_code=409,
            detail="A scrape is already running for this study. Try again once it finishes.",
        )

    if not list_sources_for_project(project_id):
        raise HTTPException(
            status_code=400,
            detail="No sources to scrape yet. Confirm at least one competitor channel before running analysis.",
        )

    run = create_pipeline_run(status="queued", stage="queued", message="Queued for execution.", project_id=project_id)
    run_id = run["id"] if run else uuid.uuid4().hex
    run_scraper_pipeline(run_id, project_id)

    finished = get_pipeline_run(run_id)
    if not finished or finished.get("status") != "success":
        error = (finished or {}).get("error") or "Scrape and enrichment did not complete."
        raise HTTPException(status_code=502, detail=f"Could not gather articles before analysis: {error}")
    return finished


@router.post("/studies/{project_id}/analyze")
def analyze(project_id: int, payload: dict = None, user: dict = Depends(require_permission("competitors.analyze"))):
    """Validate the scraped evidence, then generate one card per tracked competitor.

    `scrape` in the payload is the user's explicit choice from the "Run
    analysis" dialog: True scrapes+enriches first regardless of what's already
    there, False skips straight to analysis on whatever evidence already
    exists. Omitting it falls back to the old auto-detect behaviour (scrape
    only when the project has zero articles) for any caller that predates the
    dialog, e.g. a scheduled run.
    """
    _project_or_404(project_id)
    payload = payload or {}
    period_days = max(1, min(int(payload.get("period_days") or competitor_analysis.DEFAULT_PERIOD_DAYS), 365))
    scrape_choice = payload.get("scrape")

    scrape_run = None
    needs_scrape = scrape_choice if isinstance(scrape_choice, bool) else not project_has_articles(project_id)
    if needs_scrape:
        scrape_run = _ensure_articles(project_id)

    result = competitor_analysis.generate_findings(project_id, period_days=period_days)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return {
        **result,
        "findings": competitor_analysis.list_findings(project_id),
        "scrape_run": scrape_run,
    }


@router.get("/studies/{project_id}/findings")
def list_findings(project_id: int, impact: str | None = None, competitor_id: int | None = None,
                  history: bool = False, user: dict = Depends(require_permission("competitors.view"))):
    _project_or_404(project_id)
    return {
        "findings": competitor_analysis.list_findings(
            project_id, competitor_id=competitor_id, impact_level=impact, latest_only=not history,
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
               repeat_weekdays, first_run_at, next_run_at, last_run_at, last_run_status
        from projects where id = %s
        """,
        (int(project_id),),
    )}


@router.put("/studies/{project_id}/schedule")
def set_schedule(project_id: int, payload: dict, user: dict = Depends(require_permission("competitors.manage"))):
    """Enable recurring competitor scrapes via the existing project scheduler."""
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
               end
         where id = %s
        returning repeat_enabled, repeat_interval_value, repeat_interval_unit,
                  first_run_at, next_run_at, last_run_at, last_run_status
        """,
        (enabled, value, unit, first_run, enabled, first_run, int(project_id)),
    )
    return {"schedule": schedule}


@router.post("/studies/{project_id}/sync-sources")
def sync_sources(project_id: int, user: dict = Depends(require_permission("competitors.manage"))):
    """Reconcile project sources with the currently-valid competitor accounts."""
    _project_or_404(project_id)
    return {"sources": competitors_store.sync_project_sources(project_id)}
