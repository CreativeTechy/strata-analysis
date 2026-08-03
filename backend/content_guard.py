"""Shared guard against Google consent/interstitial and search pages, and
against Reddit/Telegram responses that are not real content, being stored as
articles.

Used in two places: the scraper (backend/scraper/spiders/source_rss.py), which
is the primary chokepoint since it decides what gets yielded as a scraped
item in the first place, and the enrichment cleaner
(backend/services/articles/enrich.py), which is a secondary safeguard for
anything that reaches it another way (for example a previously-generated
articles.json re-run through enrich.py after this guard was added).
"""

import re
from urllib.parse import urlparse

# Google's own domains never host editorial/publisher content. news.google.com
# in particular is where the "keyword" source type used to point directly at
# a search results page (see services/sources/sources_store.py's
# _derive_term_url) - Google serves a
# cookie/consent interstitial there instead of results for many requests, and
# that interstitial was being scraped as if it were an article.
BLOCKED_DOMAINS = {
    "google.com",
    "news.google.com",
    "consent.google.com",
    "accounts.google.com",
    "policies.google.com",
    "support.google.com",
}

_TITLE_PATTERNS = [
    re.compile(r"before you continue to google", re.I),
    re.compile(r"personalization settings\s*&?\s*cookies", re.I),
    re.compile(r"^sign in\s*-\s*google accounts$", re.I),
    re.compile(r"google\s*(privacy policy|terms of service)", re.I),
]


def is_blocked_domain(url):
    """True for a Google consent/search/accounts domain, however it was reached."""
    netloc = (urlparse(url or "").netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc in BLOCKED_DOMAINS or netloc.endswith(".google.com")


def is_consent_title(title):
    """True when a title matches a known Google consent/interstitial page."""
    title = (title or "").strip()
    if not title:
        return False
    return any(pattern.search(title) for pattern in _TITLE_PATTERNS)


def is_blocked_article(url, title):
    return is_blocked_domain(url) or is_consent_title(title)


def is_reddit_blocked_payload(payload):
    """True when a Reddit JSON response is an error/interstitial rather than
    a real Listing.

    Reddit's public `.json` endpoints return a plain error dict - not a
    Listing (which always has top-level `kind`/`data` keys) - for private,
    banned or quarantined subreddits/users, and for some rate-limited/blocked
    requests. Treat any of those the same as an empty listing: nothing to
    store, not an error worth failing the run over.
    """
    if not isinstance(payload, dict):
        return False
    if "error" in payload:
        return True
    if str(payload.get("reason") or "").strip().lower() in {"private", "banned", "quarantined"}:
        return True
    return False


def is_telegram_channel_unavailable(status):
    """True when a `t.me/s/<channel>` request was redirected away from the
    `/s/` preview path.

    Confirmed by hand against the live site: a channel that exists and is
    public serves the `/s/` preview directly with status 200; a handle that
    does not exist (or is not a public channel) 302-redirects to the bare
    `t.me/<handle>` app-install/contact page instead. The scraper requests
    with redirects disabled so this status is what the callback actually
    sees, rather than silently following into that unrelated page and
    scraping its boilerplate as if it were a message.
    """
    return status in (301, 302, 303, 307, 308)
