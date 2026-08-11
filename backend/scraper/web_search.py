"""General-web-search tier for "keyword" sources: Google Custom Search JSON
API client. See config.py's GOOGLE_CSE_API_KEY/GOOGLE_CSE_ENGINE_ID and
source_rss.py's start(), which crawls each returned result the same way a
"web" source is crawled (extract + follow same-domain links) - a keyword's
Google News RSS feed alone only surfaces news coverage, missing ordinary web
pages (blogs, forums, retailer/brand pages, ...) that mention the keyword.
"""

import requests

import config

CSE_URL = "https://customsearch.googleapis.com/customsearch/v1"


def google_cse_search(query, num=10):
    """Return up to `num` (max 10, the API's own per-request cap) web results
    for `query` as [{"url", "title", "snippet"}, ...]. [] if the API isn't
    configured or the request fails - callers treat this tier as best-effort,
    never blocking on it."""
    query = (query or "").strip()
    if not config.google_cse_configured() or not query:
        return []
    try:
        resp = requests.get(
            CSE_URL,
            params={
                "key": config.GOOGLE_CSE_API_KEY,
                "cx": config.GOOGLE_CSE_ENGINE_ID,
                "q": query,
                "num": max(1, min(int(num), 10)),
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results = []
    for item in data.get("items") or []:
        link = (item.get("link") or "").strip()
        if not link:
            continue
        results.append({"url": link, "title": item.get("title") or "", "snippet": item.get("snippet") or ""})
    return results
