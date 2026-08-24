"""Guard against Google consent/interstitial and search-results pages being
treated as real articles.

Only reachable through imported data now (an article split out of an uploaded
document has no URL to judge), but a JSONL export from a crawler carries
exactly these: a consent interstitial that was scraped as if it were an
article, or a `news.google.com` search page. Letting one into a competitor
study's evidence would put Google's cookie banner into a report someone plans
against, so the check stays.
"""

import re
from urllib.parse import urlparse

# Google's own domains never host editorial/publisher content.
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
    host = urlparse(str(url or "").strip()).netloc.lower()
    if not host:
        return False
    if host.startswith("www."):
        host = host[4:]
    return host in BLOCKED_DOMAINS


def is_consent_title(title):
    text = str(title or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _TITLE_PATTERNS)


def is_blocked_article(url, title):
    """True if this row is a consent/search page rather than an article."""
    return is_blocked_domain(url) or is_consent_title(title)
