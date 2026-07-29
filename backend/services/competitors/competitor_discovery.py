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
from urllib.parse import urlparse

import config
from llm_client import LLMError, chat_completion
from services.projects.project_discovery import _lightweight_fetch, _normalize_url, _search_bing, _search_duckduckgo

PROMPT_VERSION = "competitor-discovery-2026-07-27"

SIZE_TIERS = ("enterprise", "mid_market", "smb", "startup", "unknown")
TIER_WEIGHT = {"enterprise": 0, "mid_market": 1, "smb": 2, "startup": 3, "unknown": 4}

MAX_COMPETITORS = 12

DISCOVERY_SYSTEM_PROMPT = """You identify real, currently-operating competitors of a business.

Rules:
- Name only companies that actually exist. If unsure a company is real, omit it.
- `website` must be the company's own primary domain, not a directory, listicle,
  marketplace, Wikipedia page, or news article about them.
- Do not include the business itself.
- Rank by SIZE, largest first: `size_rank` 1 is the largest competitor.
- `size_tier`: enterprise (large/public/market leader), mid_market, smb, startup.
- `size_signals` must state what your size judgement is based on in short factual
  phrases, e.g. ["public company", "global footprint", "raised Series D"]. If you
  have no basis, return [].
- `why_competitor` — one sentence on the overlap with this specific business.

Return ONLY this JSON, no markdown:
{"competitors": [
  {"name": "", "website": "", "description": "", "size_tier": "enterprise",
   "size_rank": 1, "size_signals": [], "why_competitor": ""}
]}"""

ACCOUNTS_SYSTEM_PROMPT = """You list the official owned channels of a company.

Rules:
- Only channels you are confident belong to THIS company. Omit anything uncertain.
- Use canonical URLs (https://x.com/handle, https://www.linkedin.com/company/slug).
- Never guess a handle by pattern alone. If you do not know it, omit the platform.
- `confidence` 0..1 reflects how sure you are the channel is theirs.

Return ONLY this JSON, no markdown:
{"accounts": [{"platform": "x|linkedin|facebook|youtube|instagram|blog|news", "url": "", "handle": "", "confidence": 0.0}]}"""

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
