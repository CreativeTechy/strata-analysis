"""Find who the competitors are, rank them by size, and locate their accounts.

Three stages, deliberately separate:

1. `discover_competitors()` — asks the LLM for the real companies competing with
   the profiled business and shows the raw name list to the user immediately.
   Ranking is by size, because a user comparing themselves to the market cares
   about the incumbents first, and because "prioritise by size" is the only
   ordering that is stable enough to be worth showing as a rank. Live web
   corroboration is *not* run here — a fast list beats a slow one, and most
   suggestions never get tracked, so spending a fetch-plus-search per candidate
   here would mostly be wasted.

2. `verify_competitor()` — runs once a user actually tracks an AI-suggested
   competitor: the same web corroboration `discover_competitors()` used to do
   up front, now spent only on companies the user chose. Catches a hallucinated
   name or dead domain before phase 3 spends an LLM call finding its channels.

3. `discover_accounts()` — resolves each competitor's channels: owned accounts
   (site feed, X, blog, news) plus hashtags worth monitoring them by. Every
   result carries a confidence and is pre-approved (`validation_status: "valid"`),
   so it's linked as a scrape source the moment it's discovered — no manual
   confirmation step.

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
from services.competitors.countries import COUNTRIES, country_label, validate_countries
from services.projects.project_discovery import _lightweight_fetch, _normalize_url, _search_bing, _search_duckduckgo

PROMPT_VERSION = "competitor-discovery-2026-08-05"

SIZE_TIERS = ("enterprise", "mid_market", "smb", "startup", "unknown")
TIER_WEIGHT = {"enterprise": 0, "mid_market": 1, "smb": 2, "startup": 3, "unknown": 4}

MAX_COMPETITORS = 12

DISCOVERY_SYSTEM_PROMPT = load_prompt("competitor_discovery_system_prompt.txt")
ACCOUNTS_SYSTEM_PROMPT = load_prompt("competitor_accounts_system_prompt.txt")

# Restricted to platforms we can actually scrape (backend/scraper/spiders/source_rss.py
# and config.KNOWN_SOURCE_TYPES) — LinkedIn/Facebook/Instagram/YouTube are dropped
# because nothing in this app fetches them.
VALID_PLATFORMS = {"x", "hashtag", "blog", "news"}

# Phase 3 asks for several X accounts (main brand, regional, support, product
# lines) and several hashtags (branded + relevant industry ones worth
# monitoring), not just one of each — cap per platform so a verbose model
# response can't flood a competitor with low-value channels.
MAX_ACCOUNTS_PER_PLATFORM = {"x": 5, "hashtag": 8, "blog": 2, "news": 1}

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


def _ask_for_competitors(
    profile_context: str, exclude_domain: str, limit: int,
    target_countries: list[str] | None = None,
) -> list[dict]:
    directive = ""
    if target_countries:
        names = ", ".join(country_label(code) for code in target_countries)
        directive = (
            f"\n\nOnly list competitors primarily headquartered or operating in: {names}. "
            f'For each competitor, set "country" to its ISO 3166-1 alpha-2 code. If you '
            f"cannot find enough good matches inside these countries, you may include "
            f"others, but still report their true country honestly."
        )
    user_prompt = (
        f"{profile_context}\n\n"
        f"Their own domain (never list this as a competitor): {exclude_domain or 'unknown'}\n\n"
        f"List up to {limit} competitors, largest first.{directive}"
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


def _corroborate(name: str, website: str, log=None) -> dict:
    """Check a suggested competitor against the live web.

    Returns `{reachable, search_hits, resolved_website}`. A company the LLM
    invented will typically have an unreachable domain and no search presence,
    which is what lets us drop it before it reaches the user.
    """
    log = log or (lambda _msg: None)
    resolved = _normalize_url(website) if website else ""
    reachable = False
    if resolved and _is_company_site(resolved):
        log(f"{name}: checking {resolved} is reachable...")
        reachable = _reachable(resolved)
        log(f"{name}: site is {'reachable' if reachable else 'unreachable'}.")

    hits = 0
    try:
        log(f'{name}: searching DuckDuckGo for "{name}" official site...')
        results = _search_duckduckgo(f'"{name}" official site', limit=4) or []
        if not results:
            log(f"{name}: no DuckDuckGo results, falling back to Bing...")
            results = _search_bing(f'"{name}" official site', limit=4) or []
        hits = len(results)
        log(f"{name}: found {hits} search result{'' if hits == 1 else 's'}.")
        if not resolved:
            for item in results:
                candidate = _normalize_url(item.get("url") or "")
                if candidate and _is_company_site(candidate):
                    resolved = candidate
                    break
    except Exception:
        pass

    return {"reachable": reachable, "search_hits": hits, "resolved_website": resolved}


def verify_competitor(name: str, website: str | None, log=None) -> dict:
    """Phase 2: corroborate one AI-suggested competitor against the live web.

    Called when a user tracks it, not when it's first suggested — the same
    check `discover_competitors()` used to run on every candidate up front,
    now spent only on the ones actually chosen. Returns
    `{verified, reachable, search_hits, resolved_website}`; `verified` is what
    the old accept/reject rule in `discover_competitors()` used to decide.
    """
    check = _corroborate(name, website or "", log)
    verified = bool(check["resolved_website"]) and (check["reachable"] or check["search_hits"] > 0)
    return {**check, "verified": verified}


def discover_competitors(
    profile: dict, limit: int = MAX_COMPETITORS, corroborate: bool = True, log=None,
) -> dict:
    """Return `{competitors: [...], rejected: [...]}`, ranked largest first."""
    from services.competitors.business_profile_store import profile_context

    log = log or (lambda _msg: None)
    context = profile_context(profile)
    if not context:
        return {"competitors": [], "rejected": [], "error": "No business profile to compare against."}

    own_domain = _domain(profile.get("website") or "")
    target_countries = validate_countries(profile.get("target_countries"))
    filter_countries = target_countries
    log("Asking the model for competitor candidates...")
    suggestions = _ask_for_competitors(context, own_domain, min(limit, MAX_COMPETITORS), target_countries)
    if not suggestions and target_countries:
        log("No in-country candidates; retrying without the country restriction...")
        suggestions = _ask_for_competitors(context, own_domain, min(limit, MAX_COMPETITORS), None)
        filter_countries = []
    if not suggestions:
        return {"competitors": [], "rejected": [], "error": "The model returned no competitors."}
    log(f"Model suggested {len(suggestions)} candidates; checking each...")

    rejected: list[dict] = []

    # Pass 1 (cheap, sequential): filter out anything a plain field check can
    # already decide - the network is only needed for what's left.
    candidates: list[dict] = []
    for entry in suggestions:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue

        website = str(entry.get("website") or "").strip()
        domain = _domain(website)

        if domain and domain == own_domain:
            rejected.append({"name": name, "reason": "This is the user's own business."})
            continue
        if website and not _is_company_site(website):
            rejected.append({"name": name, "reason": f"{domain or website} is not a company's own site."})
            continue

        raw_country = str(entry.get("country") or "").strip().upper()
        country = raw_country if raw_country in COUNTRIES else None
        if filter_countries and country and country not in filter_countries:
            rejected.append({
                "name": name,
                "reason": f"Located in {country_label(country)}, outside the target countries.",
            })
            continue

        candidates.append({"entry": entry, "name": name, "website": website, "country": country})

    # Pass 2 (concurrent): each candidate's web corroboration is an independent
    # site fetch plus search-engine calls - run them in parallel rather than one
    # after another, the same pattern _discover_accounts_concurrently uses.
    checks: dict[int, dict] = {}
    if corroborate and candidates:
        with ThreadPoolExecutor(max_workers=min(6, len(candidates))) as pool:
            futures = {
                i: pool.submit(_corroborate, c["name"], c["website"], log)
                for i, c in enumerate(candidates)
            }
        checks = {i: future.result() for i, future in futures.items()}

    # Pass 3 (sequential, original order): the actual accept/reject decisions,
    # unchanged from before - only the corroboration call itself moved to pass 2.
    # Staying sequential and in order here is what preserves the original
    # semantics: a name already accepted earlier silently drops a later repeat,
    # and a later duplicate of an already-accepted domain still loses.
    accepted: list[dict] = []
    seen_domains: set[str] = {own_domain} if own_domain else set()
    seen_names: set[str] = set()
    for i, candidate in enumerate(candidates):
        entry = candidate["entry"]
        name = candidate["name"]
        website = candidate["website"]
        country = candidate["country"]

        if name.casefold() in seen_names:
            continue

        check = checks.get(i) or {"reachable": True, "search_hits": 0, "resolved_website": website}
        if corroborate:
            if not check["resolved_website"]:
                rejected.append({"name": name, "reason": "No reachable website found."})
                log(f"{name}: rejected — no reachable website found.")
                continue
            if not check["reachable"] and check["search_hits"] == 0:
                rejected.append({"name": name, "reason": "Could not corroborate that this company exists."})
                log(f"{name}: rejected — could not corroborate that this company exists.")
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

        log(f"{name}: accepted.")
        accepted.append({
            "name": name,
            "website": resolved or None,
            "domain": domain or None,
            "description": str(entry.get("description") or "").strip(),
            "country": country,
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
            return {"platform": "blog", "url": found[0].strip(), "handle": None,
                    "confidence": 0.9, "validation_status": "valid"}
    except Exception:
        pass
    for hint in ("/feed", "/rss.xml", "/blog/feed"):
        candidate = website.rstrip("/") + hint
        if _reachable(candidate):
            return {"platform": "blog", "url": candidate, "handle": None,
                    "confidence": 0.7, "validation_status": "valid"}
    return None


def _ask_for_accounts(name: str, website: str) -> list[dict]:
    try:
        raw = chat_completion(
            messages=[
                {"role": "system", "content": ACCOUNTS_SYSTEM_PROMPT},
                {"role": "user", "content": f"Company: {name}\nWebsite: {website or 'unknown'}"},
            ],
            temperature=0.0,
            max_tokens=1400,
            timeout=90,
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
    candidate = parts[-1] if parts[0] in {"company", "c", "user", "channel", "in", "hashtag"} else parts[0]
    return candidate if re.fullmatch(r"[A-Za-z0-9._-]{2,60}", candidate or "") else None


def discover_accounts(name: str, website: str | None, log=None) -> list[dict]:
    """Owned channels for one competitor, pre-approved (`validation_status: "valid"`)
    so they're linked as scrape sources immediately - no manual confirmation step."""
    log = log or (lambda _msg: None)
    site = str(website or "").strip()
    accounts: list[dict] = []
    seen: set[str] = set()
    counts: dict[str, int] = {}

    log(f"{name}: checking for a site feed...")
    feed = _guess_site_feed(site)
    if feed:
        log(f"{name}: found feed {feed['url']}")
        accounts.append(feed)
        seen.add(feed["url"].lower())
        counts["blog"] = counts.get("blog", 0) + 1

    if site:
        accounts.append({"platform": "news", "url": site, "handle": _domain(site),
                         "confidence": 1.0, "validation_status": "valid"})
        seen.add(site.lower())
        counts["news"] = counts.get("news", 0) + 1

    log(f"{name}: asking the model for channels — X accounts and hashtags to monitor...")
    candidates = [entry for entry in _ask_for_accounts(name, site) if isinstance(entry, dict)]
    # X handles are the riskiest guess to widen — check each is a live account
    # before it's linked as a scrape source, rather than trusting the model.
    x_urls = {
        _normalize_url(str(entry.get("url") or "").strip())
        for entry in candidates
        if str(entry.get("platform") or "").strip().lower() == "x"
    }
    reachable_x = {url for url in x_urls if url and _reachable(url)}
    dropped_x = len(x_urls) - len(reachable_x)
    if dropped_x:
        log(f"{name}: dropped {dropped_x} X handle{'' if dropped_x == 1 else 's'} that didn't resolve.")

    for entry in candidates:
        platform = str(entry.get("platform") or "").strip().lower()
        url = _normalize_url(str(entry.get("url") or "").strip())
        if platform not in VALID_PLATFORMS or not url or url.lower() in seen:
            continue
        if platform == "x" and url not in reachable_x:
            continue
        if counts.get(platform, 0) >= MAX_ACCOUNTS_PER_PLATFORM.get(platform, 1):
            continue
        seen.add(url.lower())
        counts[platform] = counts.get(platform, 0) + 1
        try:
            confidence = max(0.0, min(float(entry.get("confidence", 0.5)), 1.0))
        except (TypeError, ValueError):
            confidence = 0.5
        accounts.append({
            "platform": platform,
            "url": url,
            "handle": str(entry.get("handle") or "").strip().lstrip("@") or _handle_from_url(url),
            "confidence": confidence,
            "validation_status": "valid",
        })

    log(f"{name}: found {len(accounts)} channel{'' if len(accounts) == 1 else 's'}.")
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
            "logs": [],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
    return run_id


def get_discovery_run(run_id: str) -> dict | None:
    with _runs_lock:
        run = _runs.get(run_id)
        if not run:
            return None
        copy = dict(run)
        # A plain dict(run) still shares the same `logs` list object with the
        # live run - copy it too so a response being serialized never reads a
        # list a worker thread is concurrently appending to.
        copy["logs"] = list(run.get("logs") or [])
        return copy


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


def _append_log(run_id: str, message: str) -> None:
    """Append one real-time progress line to a run - safe to call concurrently
    from worker threads, guarded by the same lock as _update_discovery_run."""
    with _runs_lock:
        run = _runs.get(run_id)
        if run is not None:
            run.setdefault("logs", []).append({"ts": _now_iso(), "message": message})
            run["updated_at"] = _now_iso()


def _discover_accounts_concurrently(targets: list[dict], log=None) -> dict[int, list[dict]]:
    """Run discover_accounts() for each `{id, name, website}` target in parallel.

    Each target's account discovery is an independent LLM call plus a site fetch -
    run them concurrently rather than one after another.
    """
    if not targets:
        return {}
    with ThreadPoolExecutor(max_workers=min(6, len(targets))) as pool:
        futures = {
            target["id"]: pool.submit(discover_accounts, target["name"], target.get("website"), log)
            for target in targets
        }
    return {target_id: future.result() for target_id, future in futures.items()}


def run_discovery_job(run_id: str, project_id: int, profile: dict, limit: int, with_accounts: bool) -> None:
    """Background counterpart of the old synchronous discover() endpoint body.

    Phase 1 only — no live web corroboration. That check now runs per
    competitor in `verify_competitor()`, at the point a user tracks one, so
    the name list shows up as fast as the LLM call itself.
    """
    from services.competitors import competitors_store

    log = lambda msg: _append_log(run_id, msg)  # noqa: E731
    _update_discovery_run(run_id, status="running", stage="discovering",
                          message="Asking the model for competitors...")
    try:
        result = discover_competitors(profile, limit=limit, corroborate=False, log=log)
        if result.get("error") and not result.get("competitors"):
            _update_discovery_run(run_id, status="failed", stage="error",
                                  message=result["error"], error=result["error"])
            return

        records = [r for r in (competitors_store.upsert_competitor(project_id, entry) for entry in result["competitors"]) if r]

        accounts_by_id = {}
        if with_accounts and records:
            _update_discovery_run(run_id, stage="accounts",
                                  message=f"Resolving accounts for {len(records)} competitors...")
            accounts_by_id = _discover_accounts_concurrently(records, log=log)

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


def run_accounts_discovery_job(run_id: str, project_id: int, targets: list[dict]) -> None:
    """Phase 3: find channels for a given set of already-tracked competitors.

    `targets` is `[{id, name, website}, ...]` — the caller decides which competitors
    qualify (see competitor_api.py's discover_accounts_bulk, which scopes this to
    tracked competitors with no accounts yet).
    """
    from services.competitors import competitors_store

    log = lambda msg: _append_log(run_id, msg)  # noqa: E731
    _update_discovery_run(run_id, status="running", stage="accounts",
                          message=f"Finding channels for {len(targets)} competitors...")
    try:
        accounts_by_id = _discover_accounts_concurrently(targets, log=log)
        discovered = 0
        for target in targets:
            for account in accounts_by_id.get(target["id"], []):
                if competitors_store.upsert_account(target["id"], account):
                    discovered += 1

        _update_discovery_run(
            run_id, status="success", stage="done",
            message=f"Found {discovered} channel{'' if discovered == 1 else 's'} "
                    f"across {len(targets)} competitor{'' if len(targets) == 1 else 's'}.",
            discovered=discovered, rejected=[],
        )
    except Exception as exc:
        _update_discovery_run(run_id, status="failed", stage="error",
                              message="Channel discovery crashed.", error=str(exc))
