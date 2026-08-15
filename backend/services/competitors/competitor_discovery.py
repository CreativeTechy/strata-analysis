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
   (site feed, X, blog, news) plus hashtags and search keywords worth
   monitoring them by. A couple of live web searches ground the LLM call the
   same way `discover_competitors()`'s grounding does, since the model's own
   memory of a smaller or regional competitor's actual handles is exactly
   where it's weakest and most likely to hallucinate. Review/discussion pages
   (Reddit, Trustpilot, Yelp) are found the same grounded way but never asked
   of the model at all — a review-site URL isn't something a model can
   reliably recall, but it's exactly the kind of normally-indexed page search
   finds well, so `_review_candidates()` links the actual search hit directly
   (guarded by a name-overlap check, since everything here still gets linked
   as `valid` with no further confirmation). Every result carries a confidence
   and is pre-approved (`validation_status: "valid"`), so it's linked as a
   scrape source the moment it's discovered — no manual confirmation step.

Search and URL resolution reuse `project_discovery`, so there is one place that
knows how to query the web and normalise a result.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import config
from llm_client import LLMError, chat_completion
from prompt_loader import load_prompt
from services.competitors.countries import COUNTRIES, country_label, validate_countries
from services.competitors.job_runs import ACTIVE_STATUSES, JobRegistry
from services.projects.project_discovery import (
    OPINION_QUERY_SITES, _lightweight_fetch, _normalize_url, _search_bing, _search_duckduckgo,
)
from services.sources.sources_store import _derive_term_url

PROMPT_VERSION = "competitor-discovery-2026-08-07"

SIZE_TIERS = ("enterprise", "mid_market", "smb", "startup", "unknown")
TIER_WEIGHT = {"enterprise": 0, "mid_market": 1, "smb": 2, "startup": 3, "unknown": 4}

MAX_COMPETITORS = 12

DISCOVERY_SYSTEM_PROMPT = load_prompt("competitor_discovery_system_prompt.txt")
ACCOUNTS_SYSTEM_PROMPT = load_prompt("competitor_accounts_system_prompt.txt")

# Restricted to platforms we can actually scrape (backend/scraper/spiders/source_rss.py
# and config.KNOWN_SOURCE_TYPES) — LinkedIn/Facebook/Instagram/YouTube are dropped
# because nothing in this app fetches them. `reddit`/`web` are found via direct
# web-search hits (see _review_candidates), never asked of the LLM - unlike an
# X handle or hashtag, a review-site URL isn't something a model can reliably
# recall, but it's exactly the kind of normally-indexed page search engines do
# find well.
VALID_PLATFORMS = {"x", "hashtag", "keyword", "blog", "news", "reddit", "web"}

# Phase 3 asks for several X accounts (main brand, regional, support, product
# lines), several hashtags (branded + relevant industry ones worth monitoring),
# and a few search keywords (catches news coverage a hashtag or owned account
# would miss), not just one of each — cap per platform so a verbose model
# response can't flood a competitor with low-value channels. `reddit`/`web`
# come from search hits rather than the model, but are capped the same way for
# the same reason.
MAX_ACCOUNTS_PER_PLATFORM = {"x": 5, "hashtag": 8, "keyword": 5, "blog": 2, "news": 1, "reddit": 2, "web": 3}

# Always added on top of whatever the model suggests, not counted against
# MAX_ACCOUNTS_PER_PLATFORM's keyword cap above (that cap exists to bound a
# verbose model response, not these deterministic, always-wanted phrases).
AUTO_KEYWORD_SUFFIXES = ("branches", "reviews", "news", "complaints", "promotions")

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


# How many search queries to run for candidate grounding, and how many results to
# keep from each. Kept small: this is one extra round of latency in front of the
# discovery LLM call, and the point is to name real local players, not to dump a
# SERP into the prompt.
MAX_GROUNDING_QUERIES = 4
GROUNDING_RESULTS_PER_QUERY = 5


def _grounding_queries(profile: dict, target_countries: list[str]) -> list[str]:
    """Search queries whose results should name the businesses really competing.

    Built from the market/industry the profile already carries rather than the
    business's own name: searching "competitors of Starbucks" returns the global
    chains the model would have recalled anyway, whereas "best coffee shops in
    Lebanon" returns the local independents that are the whole point of this.
    """
    market = str(profile.get("market") or "").strip()
    industry = str(profile.get("industry") or "").strip()
    name = str(profile.get("name") or "").strip()
    category = market or industry
    if not category and not name:
        return []

    places = [country_label(code) for code in target_countries] or [
        str(profile.get("geography") or "").strip()
    ]
    places = [place for place in places if place]

    queries: list[str] = []
    for place in places:
        if category:
            queries.append(f"best {category} in {place}")
            queries.append(f"top {category} companies in {place}")
        if name:
            queries.append(f"{name} competitors in {place}")
    if not queries and name and category:
        queries.append(f"{name} competitors {category}")
    return queries[:MAX_GROUNDING_QUERIES]


def _search_snippets(query: str) -> list[dict]:
    try:
        results = _search_duckduckgo(query, limit=GROUNDING_RESULTS_PER_QUERY) or []
        if not results:
            results = _search_bing(query, limit=GROUNDING_RESULTS_PER_QUERY) or []
        return results
    except Exception:
        return []


def _grounding_context(profile: dict, target_countries: list[str], log=None) -> str:
    """Live search results for the profiled business's market, as prompt text.

    Empty string when search finds nothing — grounding is best-effort, and a
    failed or blocked search must degrade to the old recall-only behaviour
    rather than break discovery.
    """
    log = log or (lambda _msg: None)
    queries = _grounding_queries(profile, target_countries)
    if not queries:
        return ""

    log(f"Searching the web for who really competes in this market ({len(queries)} queries)...")
    with ThreadPoolExecutor(max_workers=min(4, len(queries))) as pool:
        futures = [pool.submit(_search_snippets, query) for query in queries]
    results = [item for future in futures for item in future.result()]

    lines: list[str] = []
    seen: set[str] = set()
    for item in results:
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if not title or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        lines.append(f"- {title}" + (f" — {snippet[:220]}" if snippet else ""))

    if not lines:
        log("Search returned nothing usable; falling back to the model's own knowledge.")
        return ""
    log(f"Collected {len(lines)} search results to ground the candidate list.")
    return "Web search results for this market:\n" + "\n".join(lines[:30])


def _ask_for_competitors(
    profile_context: str, exclude_domain: str, limit: int,
    target_countries: list[str] | None = None,
    scope: str = "all",
    grounding: str = "",
) -> list[dict]:
    """One discovery LLM call.

    `scope` is "local" or "global" when the caller is splitting the ask in two
    (see `discover_competitors`), or "all" for a single undifferentiated list.
    """
    directive = ""
    if target_countries:
        names = ", ".join(country_label(code) for code in target_countries)
        if scope == "global":
            directive = (
                f"\n\nList only large multinational or regional chains that compete with "
                f"this business inside {names}, wherever they are headquartered. "
                f'Set "country" to each company\'s true ISO 3166-1 alpha-2 home country code.'
            )
        else:
            directive = (
                f"\n\nEvery company you list MUST be primarily headquartered or operating in: "
                f"{names}. Include local and independent players — single-country chains, "
                f"regional favourites, well-known independents — not only international brands. "
                f'Set "country" to its ISO 3166-1 alpha-2 code; omit any company you cannot '
                f"place in one of these countries rather than guessing."
            )
    if grounding:
        directive += f"\n\n{grounding}"

    ordering = "largest first" if scope != "local" else "most significant first"
    user_prompt = (
        f"{profile_context}\n\n"
        f"Their own domain (never list this as a competitor): {exclude_domain or 'unknown'}\n\n"
        f"List up to {limit} competitors, {ordering}.{directive}"
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
    if not isinstance(entries, list):
        return []
    # Which ask produced an entry decides how the country screen treats it: the
    # "global" ask deliberately requests foreign-headquartered chains that trade
    # inside the target countries, so those must not then be rejected for being
    # foreign. Read back in `_screen`, never stored.
    for entry in entries:
        if isinstance(entry, dict):
            entry["_scope"] = scope
    return entries


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
    capped = min(limit, MAX_COMPETITORS)
    grounding = _grounding_context(profile, target_countries, log)

    if target_countries:
        # Two asks instead of one. A single size-ranked list spends every slot on
        # the biggest names it can recall, which structurally excludes exactly the
        # local players a country-scoped study exists to find - so the local half
        # gets its own call and its own slots, and the two are merged (existing
        # name/domain dedupe in pass 3 handles any overlap).
        local_limit = max(3, capped // 2)
        global_limit = max(3, capped - local_limit)
        log(f"Asking the model for {local_limit} local and {global_limit} large competitors...")
        with ThreadPoolExecutor(max_workers=2) as pool:
            local_future = pool.submit(
                _ask_for_competitors, context, own_domain, local_limit,
                target_countries, "local", grounding,
            )
            global_future = pool.submit(
                _ask_for_competitors, context, own_domain, global_limit,
                target_countries, "global", grounding,
            )
        suggestions = (local_future.result() or []) + (global_future.result() or [])
    else:
        log("Asking the model for competitor candidates...")
        suggestions = _ask_for_competitors(
            context, own_domain, capped, None, "all", grounding,
        )

    if not suggestions and target_countries:
        log("No in-country candidates; retrying without the country restriction...")
        suggestions = _ask_for_competitors(context, own_domain, capped, None, "all", grounding)
        filter_countries = []
    if not suggestions:
        return {"competitors": [], "rejected": [], "error": "The model returned no competitors."}
    log(f"Model suggested {len(suggestions)} candidates; checking each...")

    rejected: list[dict] = []

    # Pass 1 (cheap, sequential): filter out anything a plain field check can
    # already decide - the network is only needed for what's left.
    def _screen(countries: list[str]) -> tuple[list[dict], list[dict]]:
        kept: list[dict] = []
        dropped: list[dict] = []
        for entry in suggestions:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if not name:
                continue

            website = str(entry.get("website") or "").strip()
            domain = _domain(website)

            if domain and domain == own_domain:
                dropped.append({"name": name, "reason": "This is the user's own business."})
                continue
            if website and not _is_company_site(website):
                dropped.append({"name": name, "reason": f"{domain or website} is not a company's own site."})
                continue

            raw_country = str(entry.get("country") or "").strip().upper()
            country = raw_country if raw_country in COUNTRIES else None
            if countries and entry.get("_scope") != "global":
                # A blank/unrecognised country used to pass straight through, which
                # is how globals with no country field filled a country-scoped
                # study. With a target country set, unplaceable means rejected.
                if not country:
                    dropped.append({"name": name, "reason": "No country given, so it cannot be placed in the target countries."})
                    continue
                if country not in countries:
                    dropped.append({
                        "name": name,
                        "reason": f"Located in {country_label(country)}, outside the target countries.",
                    })
                    continue

            # Where this candidate actually competes with the user's business,
            # as opposed to `country` (its home base). A "local" entry was
            # screened above to already be inside the target countries, so its
            # home country is where it competes. A "global" entry (McDonald's
            # for a Lebanon study) was asked for precisely because it competes
            # *inside* the target countries regardless of where it's from, so
            # that's what belongs here, not its US headquarters.
            if entry.get("_scope") == "global" and countries:
                operates_in = list(countries)
            elif country:
                operates_in = [country]
            else:
                operates_in = list(countries) if countries else []

            kept.append({
                "entry": entry, "name": name, "website": website,
                "country": country, "operates_in_countries": operates_in,
            })
        return kept, dropped

    candidates, rejected = _screen(filter_countries)
    if filter_countries and not candidates:
        # Every suggestion failed the country screen - a list the user can judge
        # beats an empty one, so fall back to the unfiltered screen rather than
        # returning nothing.
        log("No candidate passed the country filter; keeping the unfiltered list instead.")
        filter_countries = []
        candidates, rejected = _screen([])

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
        operates_in_countries = candidate["operates_in_countries"]

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
            "operates_in_countries": operates_in_countries,
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


# Phase 3's own grounding, mirroring _grounding_context (Phase 1) but scoped to
# one competitor's channels rather than the whole market. Kept to 2 queries -
# unlike Phase 1's single grounding pass shared across every candidate, this
# runs once per competitor (already fanned out up to 6-wide by
# _discover_accounts_concurrently), so each extra query multiplies real
# search-engine load.
ACCOUNT_GROUNDING_QUERIES = 2


def _account_grounding_queries(name: str) -> list[str]:
    if not name:
        return []
    return [f"{name} twitter OR X account", f"{name} hashtag campaign"][:ACCOUNT_GROUNDING_QUERIES]


def _account_grounding_context(name: str, log=None) -> str:
    """Live search results for one competitor's own channels, as prompt text.

    Empty string when search finds nothing — grounding is best-effort here too,
    same as Phase 1: a failed or blocked search must degrade to the model's own
    recall rather than break discovery.
    """
    log = log or (lambda _msg: None)
    queries = _account_grounding_queries(name)
    if not queries:
        return ""

    log(f"{name}: searching the web for their real accounts and hashtags...")
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = [pool.submit(_search_snippets, query) for query in queries]
    results = [item for future in futures for item in future.result()]

    lines: list[str] = []
    seen: set[str] = set()
    for item in results:
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if not title or title.casefold() in seen:
            continue
        seen.add(title.casefold())
        lines.append(f"- {title}" + (f" — {snippet[:220]}" if snippet else ""))

    if not lines:
        log(f"{name}: search returned nothing usable; falling back to the model's own knowledge.")
        return ""
    log(f"{name}: found {len(lines)} search result{'' if len(lines) == 1 else 's'} to ground channel discovery.")
    return "Web search results for this company's channels:\n" + "\n".join(lines[:20])


def _name_overlap_ok(name: str, text: str) -> bool:
    """True when enough of `name`'s words show up in `text` to trust a search
    hit is really about this competitor rather than a same-named unrelated
    result — everything `discover_accounts()` finds is linked as `valid`
    immediately, so this is the only check standing between a search hit and
    it being linked as a source.
    """
    name_words = _words(name)
    if not name_words:
        return False
    overlap = name_words & _words(text)
    return len(overlap) >= max(1, (len(name_words) + 1) // 2)


def _review_candidates(name: str, log=None) -> list[dict]:
    """Third-party pages actually about this competitor — review sites and
    discussion threads — found from real search hits rather than asked of the
    model: unlike an X handle or a hashtag, a review-site URL isn't something
    a model can reliably recall, but it's exactly the kind of normally-indexed
    page a search engine finds well. Reuses the same site list the general
    project-source discovery already searches (`OPINION_QUERY_SITES`).
    """
    log = log or (lambda _msg: None)
    if not name:
        return []
    queries = {site: f"site:{site} {name}" for site in OPINION_QUERY_SITES}
    log(f"{name}: searching for review and discussion pages...")
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        futures = {site: pool.submit(_search_snippets, query) for site, query in queries.items()}
    candidates = []
    for site, future in futures.items():
        results = future.result() or []
        # Only the best-matching hit per site — a flood of loosely-related
        # results from one review site would be noise, not more coverage.
        match = next(
            (r for r in results if _name_overlap_ok(name, f"{r.get('title', '')} {r.get('snippet', '')}")),
            None,
        )
        if not match or not match.get("url"):
            continue
        candidates.append({
            "platform": "reddit" if "reddit.com" in site else "web",
            "url": match["url"],
            "handle": None,
            "confidence": 0.6,
            "validation_status": "valid",
        })
    log(f"{name}: found {len(candidates)} matching review/discussion page{'' if len(candidates) == 1 else 's'}."
        if candidates else f"{name}: no matching review or discussion pages found.")
    return candidates


def _ask_for_accounts(
    name: str, website: str, target_countries: list[str] | None = None, grounding: str = "",
) -> list[dict]:
    directive = ""
    if target_countries:
        names = ", ".join(country_label(code) for code in target_countries)
        directive = (
            f"\n\nThis company is being tracked as a competitor specifically inside: "
            f"{names}. Prefer channels relevant there — the main global brand account, "
            f"or a regional account that actually covers {names} — over an account "
            f"scoped to somewhere else. Skip a regional handle for a different single "
            f"country (e.g. a Canada-only account is no use for a Lebanon-scoped study) "
            f"unless it is the only account you know of."
        )
    if grounding:
        directive += f"\n\n{grounding}"
    try:
        raw = chat_completion(
            messages=[
                {"role": "system", "content": ACCOUNTS_SYSTEM_PROMPT},
                {"role": "user", "content": f"Company: {name}\nWebsite: {website or 'unknown'}{directive}"},
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


_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(str(text or "").casefold()))


def _foreign_region_hit(handle: str, url: str, target_countries: list[str] | None) -> str | None:
    """Name of a country this channel looks scoped to, when that isn't one of
    the target countries — catches something like "@McD_Canada" surviving into
    a Lebanon-scoped study. `_ask_for_accounts` is told to avoid these; this is
    the backstop for when it doesn't listen.

    Only single-word country names are checked, to keep false positives rare —
    a multi-word name like "United States" would otherwise false-match on a
    bare mention of "united" or "states".
    """
    if not target_countries:
        return None
    words = _words(f"{handle} {url}")
    if not words:
        return None
    target_words = {word for code in target_countries for word in _words(country_label(code))}
    for code, name in COUNTRIES.items():
        if code in target_countries:
            continue
        name_words = _words(name)
        if len(name_words) != 1:
            continue
        word = next(iter(name_words))
        if len(word) > 3 and word in words and word not in target_words:
            return name
    return None


def discover_accounts(
    name: str, website: str | None, target_countries: list[str] | None = None, log=None,
) -> list[dict]:
    """Owned channels for one competitor, pre-approved (`validation_status: "valid"`)
    so they're linked as scrape sources immediately - no manual confirmation step.

    `target_countries` is the study's target countries, when set: they steer the
    model towards channels relevant to competing there (see `_ask_for_accounts`)
    and, as a backstop, get a mismatched regional handle dropped outright rather
    than linked as a source that won't benefit this study.
    """
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

    grounding = _account_grounding_context(name, log)
    log(f"{name}: asking the model for channels — X accounts, hashtags, and keywords to monitor...")
    candidates = [
        entry for entry in _ask_for_accounts(name, site, target_countries, grounding) if isinstance(entry, dict)
    ]
    # Review/discussion pages are found directly from search hits, not asked
    # of the model — see _review_candidates. They join the same list so the
    # dedup/per-platform-cap/region-mismatch handling below applies uniformly.
    candidates.extend(_review_candidates(name, log))
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

    dropped_region = 0
    for entry in candidates:
        platform = str(entry.get("platform") or "").strip().lower()
        handle = str(entry.get("handle") or "").strip()
        # `keyword` has no canonical URL of its own — the model is asked to
        # give the search phrase in `handle`, and the real (Google News RSS
        # search) URL is derived from it, the same way a manually-added
        # keyword source is, rather than trusting whatever `url` the model
        # made up for it.
        if platform == "keyword":
            url = _derive_term_url("keyword", handle or str(entry.get("url") or "").strip())
        else:
            url = _normalize_url(str(entry.get("url") or "").strip())
        if platform not in VALID_PLATFORMS or not url or url.lower() in seen:
            continue
        if platform == "x" and url not in reachable_x:
            continue
        if _foreign_region_hit(handle, url, target_countries):
            dropped_region += 1
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
            "handle": handle.lstrip("@") or _handle_from_url(url),
            "confidence": confidence,
            "validation_status": "valid",
        })
    if dropped_region:
        log(f"{name}: dropped {dropped_region} channel{'' if dropped_region == 1 else 's'} "
            f"scoped to a different region than this study targets.")

    # Guaranteed keyword coverage on top of whatever the model suggested -
    # see AUTO_KEYWORD_SUFFIXES above.
    for suffix in AUTO_KEYWORD_SUFFIXES:
        term = f"{name} {suffix}"
        url = _derive_term_url("keyword", term)
        if not url or url.lower() in seen:
            continue
        seen.add(url.lower())
        accounts.append({
            "platform": "keyword",
            "url": url,
            "handle": term,
            "confidence": 1.0,
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
# FastAPI BackgroundTask instead of inline in the request handler, tracked in
# the shared in-process registry (services/competitors/job_runs.py) that
# competitor analysis now uses too - see that module for why these runs are not
# persisted the way the scrape pipeline's are.
_discovery_runs = JobRegistry("Queued for competitor discovery.")

ACTIVE_DISCOVERY_STATUSES = ACTIVE_STATUSES


def create_discovery_run(project_id: int) -> str:
    return _discovery_runs.create(project_id, discovered=0, rejected=[])


def get_discovery_run(run_id: str) -> dict | None:
    return _discovery_runs.get(run_id)


def get_active_discovery_run(project_id: int) -> dict | None:
    return _discovery_runs.active_for_project(project_id)


_update_discovery_run = _discovery_runs.update
_append_log = _discovery_runs.append_log


def _discover_accounts_concurrently(
    targets: list[dict], target_countries: list[str] | None = None, log=None,
) -> dict[int, list[dict]]:
    """Run discover_accounts() for each `{id, name, website}` target in parallel.

    Each target's account discovery is an independent LLM call plus a site fetch -
    run them concurrently rather than one after another.
    """
    if not targets:
        return {}
    with ThreadPoolExecutor(max_workers=min(6, len(targets))) as pool:
        futures = {
            target["id"]: pool.submit(
                discover_accounts, target["name"], target.get("website"), target_countries, log,
            )
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
            target_countries = validate_countries(profile.get("target_countries"))
            accounts_by_id = _discover_accounts_concurrently(records, target_countries=target_countries, log=log)

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
    from services.competitors.business_profile_store import get_profile

    log = lambda msg: _append_log(run_id, msg)  # noqa: E731
    _update_discovery_run(run_id, status="running", stage="accounts",
                          message=f"Finding channels for {len(targets)} competitors...")
    try:
        profile = get_profile(project_id) or {}
        target_countries = validate_countries(profile.get("target_countries"))
        accounts_by_id = _discover_accounts_concurrently(targets, target_countries=target_countries, log=log)
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
