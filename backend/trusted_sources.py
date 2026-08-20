"""Curated allowlist of well-known, editorially-reputable news domains.

An article is "verified" when its actual publisher domain - not its
configured `sources` row, which for `keyword`/`hashtag` sources can resolve
to a different publisher per article - is on this list. Same domain
normalization as content_guard.py's BLOCKED_DOMAINS, but as an allowlist
instead of a blocklist.

Deliberately conservative and non-exhaustive - a starting set of major wire
services and internationally recognized outlets, exact host match only (plus
subdomains). Add to TRUSTED_DOMAINS as needed.
"""

from urllib.parse import urlparse

TRUSTED_DOMAINS = {
    # Wire services
    "reuters.com", "apnews.com", "afp.com", "upi.com",
    # Broadcast / international
    "bbc.com", "bbc.co.uk", "npr.org", "pbs.org", "cnn.com", "nbcnews.com",
    "abcnews.go.com", "cbsnews.com", "aljazeera.com", "dw.com", "france24.com",
    "euronews.com", "skynews.com",
    # Major newspapers / magazines
    "nytimes.com", "washingtonpost.com", "wsj.com", "theguardian.com",
    "usatoday.com", "latimes.com", "chicagotribune.com", "ft.com",
    "economist.com", "time.com", "newsweek.com", "theatlantic.com",
    "bloomberg.com", "forbes.com", "politico.com", "axios.com", "thehill.com",
    # Tech / science
    "techcrunch.com", "wired.com", "arstechnica.com", "theverge.com",
    "nature.com", "science.org",
}


def is_trusted_domain(url):
    """True when `url`'s host (or a subdomain of it) is a known reputable
    publisher domain."""
    netloc = (urlparse(url or "").netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if not netloc:
        return False
    if netloc in TRUSTED_DOMAINS:
        return True
    return any(netloc.endswith(f".{domain}") for domain in TRUSTED_DOMAINS)
