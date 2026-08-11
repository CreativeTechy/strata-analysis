"""GDELT DOC 2.0 API client - a free, no-key news-search tier for "keyword"
sources, queried alongside their Google News RSS feed. See config.py's
GDELT_ENABLED and source_rss.py's start(), which fetches each returned
article URL directly (these are already specific article hits, not
general-web landing pages, unlike the Google CSE tier in web_search.py).
"""

import time

import requests

import config

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# GDELT's own stated limit is "one every 5 seconds" (returned as a 429 body),
# but it has been observed 429-ing even at exactly that spacing - keyword
# sources call gdelt_search() once each from a single spider run, in a tight
# loop with no delay of their own, so a safety margin above the stated
# minimum meaningfully cuts down on 429s without it.
MIN_REQUEST_INTERVAL_SECONDS = 8.0
_last_request_at = 0.0


def _throttle():
    global _last_request_at
    wait = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    _last_request_at = time.monotonic()


def gdelt_search(query, max_records=10):
    """Return up to `max_records` (capped at 250, the API's own limit) news
    articles for `query` as [{"url", "title", "seendate", "domain"}, ...].
    [] if disabled, empty, or the request fails - callers treat this tier as
    best-effort, same as the Google CSE tier."""
    query = (query or "").strip()
    if not config.GDELT_ENABLED or not query:
        return []
    # Multi-word terms need to be quoted as an exact phrase, or GDELT parses
    # each word as a separate AND'd term instead of the intended phrase.
    search_term = f'"{query}"' if " " in query else query
    _throttle()
    try:
        resp = requests.get(
            GDELT_DOC_URL,
            params={
                "query": search_term,
                "mode": "artlist",
                "format": "json",
                "maxrecords": max(1, min(int(max_records), 250)),
                "sort": "hybridrel",
            },
            timeout=20,
            # GDELT has been observed rejecting bare/generic clients - a
            # normal browser UA avoids that, same reasoning as the spider's
            # own USER_AGENT setting.
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results = []
    for item in (data or {}).get("articles") or []:
        link = (item.get("url") or "").strip()
        if not link:
            continue
        results.append(
            {
                "url": link,
                "title": item.get("title") or "",
                "seendate": item.get("seendate") or "",
                "domain": item.get("domain") or "",
            }
        )
    return results
