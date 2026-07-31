"""Find who the competitors are, rank them by size, and locate their accounts.

Two stages, deliberately separate:

1. `discover_competitors()` — asks the LLM for the real companies competing with
   the profiled business, then corroborates each against live web search so a
   hallucinated company or a dead domain is dropped before a human ever sees it.
   Ranking is by size, because a user comparing themselves to the market cares
   about the incumbents first, and because "prioritise by size" is the only
   ordering that is stable enough to be worth showing as a rank.

2. `discover_accounts()` — resolves each competitor's owned channels (site feed,
   X, LinkedIn, Facebook, YouTube, blog). Handle guessing is unreliable, so every
   result carries a confidence and lands as `pending`: nothing reaches analysis
   until it is validated. Attributing another company's posts to a competitor
   would put false activity into a report someone plans against.

Search and URL resolution reuse `project_discovery`, so there is one place that
knows how to query the web and normalise a result.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

import config
from llm_client import LLMError, chat_completion
from prompt_loader import load_prompt
from services.projects.project_discovery import _lightweight_fetch, _normalize_url, _search_bing, _search_duckduckgo

PROMPT_VERSION = "competitor-discovery-2026-07-27"

SIZE_TIERS = ("enterprise", "mid_market", "smb", "startup", "unknown")
TIER_WEIGHT = {"enterprise": 0, "mid_market": 1, "smb": 2, "startup": 3, "unknown": 4}

MAX_COMPETITORS = 12

DISCOVERY_SYSTEM_PROMPT = load_prompt("competitor_discovery_system_prompt.txt")
ACCOUNTS_SYSTEM_PROMPT = load_prompt("competitor_accounts_system_prompt.txt")

VALID_PLATFORMS = {"x", "linkedin", "facebook", "youtube", "instagram", "blog", "news"}

# Hosts that are never a company's own site, so never a competitor "website".
NON_COMPANY_HOSTS = {
    "wikipedia.org", "linkedin.com", "crunchbase.com", "glassdoor.com",
    "indeed.com", "facebook.com", "x.com", "twitter.com", "youtube.com",
    "instagram.com", "medium.com", "reddit.com", "quora.com", "g2.com",
    "capterra.com", "trustpilot.com", "bloomberg.com", "reuters.com",
    "forbes.com", "techcrunch.com", "producthunt.com", "github.com",
}


def _strip_fences(text: str) -> str:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _domain(url: str) -> str:
    url = str(url or "").strip()
    if url and "://" not in url:
        # A bare domain like "kfc.com" (no scheme) has nothing for urlparse to
        # put in `.netloc` - the "//" prefix makes it parse as a network-path
        # reference so the host still comes out right.
        url = f"//{url}"
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _is_company_site(url: str) -> bool:
    host = _domain(url)
    if not host or "." not in host:
        return False
    return not any(host == bad or host.endswith(f".{bad}") for bad in NON_COMPANY_HOSTS)


def _as_list(value, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:limit]:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _ask_for_competitors(profile_context: str, exclude_domain: str, limit: int) -> list[dict]:
    user_prompt = (
        f"{profile_context}\n\n"
        f"Their own domain (never list this as a competitor): {exclude_domain or 'unknown'}\n\n"
        f"List up to {limit} competitors, largest first."
    )
    try:
        raw = chat_completion(
            messages=[
                {"role": "system", "content": DISCOVERY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=6000,
            timeout=120,
        )
        parsed = json.loads(_strip_fences(raw))
    except (LLMError, json.JSONDecodeError, ValueError) as exc:
        print(f"  competitor discovery failed: {exc}")
        return []

    entries = parsed.get("competitors") if isinstance(parsed, dict) else None
    return entries if isinstance(entries, list) else []


def _reachable(url: str) -> bool:
    """True when a URL answers with a non-error status.

    `_lightweight_fetch` returns {url, content_type, status_code} or None — it has
    no boolean success field, so the status has to be inspected here.
    """
    try:
        fetched = _lightweight_fetch(url)
    except Exception:
        return False
    if not fetched:
        return False
    try:
        return int(fetched.get("status_code") or 0) < 400
    except (TypeError, ValueError):
        return False


def _corroborate(name: str, website: str) -> dict:
    """Check a suggested competitor against the live web.

    Returns `{reachable, search_hits, resolved_website}`. A company the LLM
    invented will typically have an unreachable domain and no search presence,
    which is what lets us drop it before it reaches the user.
    """
    resolved = _normalize_url(website) if website else ""
    reachable = False
    if resolved and _is_company_site(resolved):
        reachable = _reachable(resolved)

    hits = 0
    try:
        results = _search_duckduckgo(f'"{name}" official site', limit=4) or []
        if not results:
            results = _search_bing(f'"{name}" official site', limit=4) or []
        hits = len(results)
        if not resolved:
            for item in results:
                candidate = _normalize_url(item.get("url") or "")
                if candidate and _is_company_site(candidate):
                    resolved = candidate
                    break
    except Exception:
        pass

    return {"reachable": reachable, "search_hits": hits, "resolved_website": resolved}


def discover_competitors(profile: dict, limit: int = MAX_COMPETITORS, corroborate: bool = True) -> dict:
    """Return `{competitors: [...], rejected: [...]}`, ranked largest first."""
    from services.competitors.business_profile_store import profile_context

    context = profile_context(profile)
    if not context:
        return {"competitors": [], "rejected": [], "error": "No business profile to compare against."}

    own_domain = _domain(profile.get("website") or "")
    suggestions = _ask_for_competitors(context, own_domain, min(limit, MAX_COMPETITORS))
    if not suggestions:
        return {"competitors": [], "rejected": [], "error": "The model returned no competitors."}

    accepted: list[dict] = []
    rejected: list[dict] = []
    seen_domains: set[str] = {own_domain} if own_domain else set()
    seen_names: set[str] = set()

    for entry in suggestions:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name or name.casefold() in seen_names:
            continue

        website = str(entry.get("website") or "").strip()
        domain = _domain(website)

        if domain and domain == own_domain:
            rejected.append({"name": name, "reason": "This is the user's own business."})
            continue
        if website and not _is_company_site(website):
            rejected.append({"name": name, "reason": f"{domain or website} is not a company's own site."})
            continue

        check = {"reachable": True, "search_hits": 0, "resolved_website": website}
        if corroborate:
            check = _corroborate(name, website)
            if not check["resolved_website"]:
                rejected.append({"name": name, "reason": "No reachable website found."})
                continue
            if not check["reachable"] and check["search_hits"] == 0:
                rejected.append({"name": name, "reason": "Could not corroborate that this company exists."})
                continue

        resolved = check["resolved_website"] or website
        domain = _domain(resolved)
        if domain and domain in seen_domains:
            continue
        if domain:
            seen_domains.add(domain)
        seen_names.add(name.casefold())

        tier = str(entry.get("size_tier") or "unknown").strip().lower()
        if tier not in SIZE_TIERS:
            tier = "unknown"

        try:
            stated_rank = int(entry.get("size_rank"))
        except (TypeError, ValueError):
            stated_rank = None

        accepted.append({
            "name": name,
            "website": resolved or None,
            "domain": domain or None,
            "description": str(entry.get("description") or "").strip(),
            "size_tier": tier,
            "stated_rank": stated_rank,
            "size_signals": {
                "basis": _as_list(entry.get("size_signals")),
                "why_competitor": str(entry.get("why_competitor") or "").strip(),
                "search_hits": check["search_hits"],
                "site_reachable": check["reachable"],
            },
            "discovery_source": "ai",
        })

    # Final ordering: tier first (an enterprise outranks a startup regardless of
    # what rank the model claimed), then the model's own ranking, then name so the
    # result is stable across identical runs.
    accepted.sort(key=lambda item: (
        TIER_WEIGHT.get(item["size_tier"], 4),
        item["stated_rank"] if item["stated_rank"] is not None else 999,
        item["name"].casefold(),
    ))
    for index, item in enumerate(accepted, start=1):
        item["size_rank"] = index
        item.pop("stated_rank", None)

    return {"competitors": accepted, "rejected": rejected, "error": None}


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
_FEED_HINTS = ("/feed", "/rss", "/atom", ".xml", "/blog/feed")


def _guess_site_feed(website: str) -> dict | None:
    """The company's own feed, if it advertises one. High confidence when found."""
    if not website:
        return None
    try:
        from trafilatura.feeds import find_feed_urls

        found = find_feed_urls(website)
        if isinstance(found, list) and found:
            return {"platform": "blog", "url": found[0].strip(), "handle": None, "confidence": 0.9}
    except Exception:
        pass
    for hint in ("/feed", "/rss.xml", "/blog/feed"):
        candidate = website.rstrip("/") + hint
        if _reachable(candidate):
            return {"platform": "blog", "url": candidate, "handle": None, "confidence": 0.7}
    return None


def _ask_for_accounts(name: str, website: str) -> list[dict]:
    try:
        raw = chat_completion(
            messages=[
                {"role": "system", "content": ACCOUNTS_SYSTEM_PROMPT},
                {"role": "user", "content": f"Company: {name}\nWebsite: {website or 'unknown'}"},
            ],
            temperature=0.0,
            max_tokens=700,
            timeout=60,
        )
        parsed = json.loads(_strip_fences(raw))
    except (LLMError, json.JSONDecodeError, ValueError) as exc:
        print(f"  account discovery failed for {name}: {exc}")
        return []
    entries = parsed.get("accounts") if isinstance(parsed, dict) else None
    return entries if isinstance(entries, list) else []


def _handle_from_url(url: str) -> str | None:
    path = urlparse(str(url or "")).path.strip("/")
    if not path:
        return None
    parts = [segment for segment in path.split("/") if segment]
    if not parts:
        return None
    candidate = parts[-1] if parts[0] in {"company", "c", "user", "channel", "in"} else parts[0]
    return candidate if re.fullmatch(r"[A-Za-z0-9._-]{2,60}", candidate or "") else None


def discover_accounts(name: str, website: str | None) -> list[dict]:
    """Owned channels for one competitor. Every entry needs validation before use."""
    site = str(website or "").strip()
    accounts: list[dict] = []
    seen: set[str] = set()

    feed = _guess_site_feed(site)
    if feed:
        accounts.append(feed)
        seen.add(feed["url"].lower())

    if site:
        accounts.append({"platform": "news", "url": site, "handle": _domain(site),
                         "confidence": 1.0})
        seen.add(site.lower())

    for entry in _ask_for_accounts(name, site):
        if not isinstance(entry, dict):
            continue
        platform = str(entry.get("platform") or "").strip().lower()
        url = _normalize_url(str(entry.get("url") or "").strip())
        if platform not in VALID_PLATFORMS or not url or url.lower() in seen:
            continue
        seen.add(url.lower())
        try:
            confidence = max(0.0, min(float(entry.get("confidence", 0.5)), 1.0))
        except (TypeError, ValueError):
            confidence = 0.5
        accounts.append({
            "platform": platform,
            "url": url,
            "handle": str(entry.get("handle") or "").strip().lstrip("@") or _handle_from_url(url),
            "confidence": confidence,
        })

    return accounts


def discovery_model() -> str:
    return config.LLM_CHAT_MODEL


# --------------------------------------------------------------------------- #
# Background job
# --------------------------------------------------------------------------- #
# Discovery chains an LLM call, live web corroboration per candidate, and (with
# with_accounts) a further LLM call per competitor - easily minutes end to end
# once the model is running slow, well past any gateway timeout. It runs as a
# FastAPI BackgroundTask instead of inline in the request handler, tracked here
# in-memory (in-process, not Postgres) since it's a one-shot onboarding step the
# user watches live, not a durable scheduled job like the scrape pipeline - if
# the backend restarts mid-run the UI just needs to let the user retry.
_runs_lock = threading.Lock()
_runs: dict[str, dict] = {}

ACTIVE_DISCOVERY_STATUSES = ("queued", "running")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_discovery_run(project_id: int) -> str:
    run_id = uuid.uuid4().hex
    with _runs_lock:
        _runs[run_id] = {
            "run_id": run_id,
            "project_id": project_id,
            "status": "queued",
            "stage": "queued",
            "message": "Queued for competitor discovery.",
            "error": None,
            "discovered": 0,
            "rejected": [],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
    return run_id


def get_discovery_run(run_id: str) -> dict | None:
    with _runs_lock:
        run = _runs.get(run_id)
        return dict(run) if run else None


def get_active_discovery_run(project_id: int) -> dict | None:
    with _runs_lock:
        for run in _runs.values():
            if run["project_id"] == project_id and run["status"] in ACTIVE_DISCOVERY_STATUSES:
                return dict(run)
    return None


def _update_discovery_run(run_id: str, **fields) -> None:
    with _runs_lock:
        run = _runs.get(run_id)
        if run is not None:
            run.update(fields, updated_at=_now_iso())


def run_discovery_job(run_id: str, project_id: int, profile: dict, limit: int, with_accounts: bool) -> None:
    """Background counterpart of the old synchronous discover() endpoint body."""
    from services.competitors import competitors_store

    _update_discovery_run(run_id, status="running", stage="discovering",
                          message="Asking the model for competitors...")
    try:
        result = discover_competitors(profile, limit=limit)
        if result.get("error") and not result.get("competitors"):
            _update_discovery_run(run_id, status="failed", stage="error",
                                  message=result["error"], error=result["error"])
            return

        records = [r for r in (competitors_store.upsert_competitor(project_id, entry) for entry in result["competitors"]) if r]

        accounts_by_id = {}
        if with_accounts and records:
            # Each competitor's account discovery is an independent LLM call plus
            # a site fetch - run them concurrently rather than one after another.
            _update_discovery_run(run_id, stage="accounts",
                                  message=f"Resolving accounts for {len(records)} competitors...")
            with ThreadPoolExecutor(max_workers=min(6, len(records))) as pool:
                futures = {
                    record["id"]: pool.submit(discover_accounts, record["name"], record.get("website"))
                    for record in records
                }
            accounts_by_id = {record_id: future.result() for record_id, future in futures.items()}

        for record in records:
            for account in accounts_by_id.get(record["id"], []):
                competitors_store.upsert_account(record["id"], account)

        competitors_store.rerank_competitors(project_id)
        _update_discovery_run(
            run_id, status="success", stage="done",
            message=f"Discovered {len(records)} competitors.",
            discovered=len(records), rejected=result.get("rejected") or [],
        )
    except Exception as exc:
        _update_discovery_run(run_id, status="failed", stage="error",
                              message="Competitor discovery crashed.", error=str(exc))
