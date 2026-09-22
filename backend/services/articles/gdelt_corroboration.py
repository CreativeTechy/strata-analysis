"""Article-level cross-source coverage signals from the public GDELT DOC API.

GDELT is a news index, not a fact checker.  A match only shows that another
domain published a closely matching story; it does not prove that the claim is
true or that the publishers are independent.  Checks are initiated explicitly
through the API rather than being part of document ingestion, preserving the
product's offline-by-default behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import config
import db
from psycopg.types.json import Jsonb


STATUS_BROAD = "broad_coverage"
STATUS_SOME = "some_coverage"
STATUS_NONE = "no_coverage_found"
class GdeltError(RuntimeError):
    """A safe, user-facing GDELT lookup failure."""


def normalize_domain(value) -> str | None:
    """Return a comparable ASCII hostname from a URL or bare domain."""
    text = str(value or "").strip()
    if not text or text.lower().startswith("document://"):
        return None
    candidate = text if "://" in text else f"//{text}"
    try:
        hostname = (urlsplit(candidate).hostname or "").strip().lower().rstrip(".")
        if hostname.startswith("www."):
            hostname = hostname[4:]
        if not hostname or "." not in hostname or " " in hostname:
            return None
        return hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return None


def _title_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w'-]+", str(value or "").casefold(), flags=re.UNICODE)
        if len(token) > 2
    }


def _title_overlap(left: str, right: str) -> float:
    expected = _title_tokens(left)
    candidate = _title_tokens(right)
    if not expected or not candidate:
        return 0.0
    return len(expected & candidate) / len(expected)


def build_query(title: str) -> str:
    """Build a conservative exact-phrase query from an article title."""
    words = re.findall(r"[\w'-]+", str(title or "").strip(), flags=re.UNICODE)
    if len(words) < 3:
        raise ValueError("The article title is too short for a useful coverage check.")
    phrase = " ".join(words[:12])
    return f'"{phrase}"'


def summarize_results(article: dict, payload: dict, query: str) -> dict:
    """Reduce GDELT results to distinct-domain, title-matched evidence."""
    provenance = article.get("source_provenance")
    original_domain = normalize_domain(provenance.get("original_url")) if isinstance(provenance, dict) else None
    original_domain = (
        original_domain
        or normalize_domain(article.get("source_domain"))
        or normalize_domain(article.get("url"))
        or normalize_domain(article.get("source_url"))
    )
    matches_by_domain: dict[str, dict] = {}

    for raw in payload.get("articles") or []:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()
        try:
            parsed_url = urlsplit(url)
        except ValueError:
            continue
        if parsed_url.scheme not in {"http", "https"}:
            continue
        domain = normalize_domain(url)
        if not domain or domain == original_domain:
            continue
        title = str(raw.get("title") or "").strip()
        overlap = _title_overlap(article.get("title") or "", title)
        if overlap < config.GDELT_MIN_TITLE_OVERLAP:
            continue
        candidate = {
            "domain": domain,
            "title": title,
            "url": url,
            "seen_at": raw.get("seendate"),
            "language": raw.get("language"),
            "source_country": raw.get("sourcecountry"),
            "title_overlap": round(overlap, 3),
        }
        previous = matches_by_domain.get(domain)
        if previous is None or candidate["title_overlap"] > previous["title_overlap"]:
            matches_by_domain[domain] = candidate

    matches = sorted(matches_by_domain.values(), key=lambda item: (-item["title_overlap"], item["domain"]))
    domain_count = len(matches)
    if domain_count >= config.GDELT_BROAD_COVERAGE_DOMAINS:
        status = STATUS_BROAD
        reason = f"Closely matching coverage was found on {domain_count} other domains."
    elif domain_count:
        status = STATUS_SOME
        reason = f"Closely matching coverage was found on {domain_count} other domain{'s' if domain_count != 1 else ''}."
    else:
        status = STATUS_NONE
        reason = "No closely matching coverage was found in the available results."

    return {
        "status": status,
        "reason": reason,
        "query": query,
        "matching_domain_count": domain_count,
        "matches": matches[: config.GDELT_STORED_MATCHES],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "caveat": "Cross-source coverage is not proof that a claim is true or that the sources are independent.",
    }


def _fetch(query: str) -> dict:
    params = urlencode({
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": config.GDELT_MAX_RECORDS,
        "sort": "HybridRel",
    })
    request = Request(
        f"{config.GDELT_DOC_API_URL}?{params}",
        headers={"Accept": "application/json", "User-Agent": "StrataAnalysis/1.0"},
    )
    try:
        with urlopen(request, timeout=config.GDELT_TIMEOUT_SECONDS) as response:
            body = response.read(config.GDELT_MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise GdeltError("The coverage service is temporarily unavailable. Please try again later.") from exc
    if len(body) > config.GDELT_MAX_RESPONSE_BYTES:
        raise GdeltError("The coverage service returned more data than the safety limit allows.")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GdeltError("The coverage service returned an unreadable response.") from exc
    if not isinstance(payload, dict):
        raise GdeltError("The coverage service returned an unexpected response.")
    return payload


def check_article(article_id: int) -> dict:
    article = db.fetch_one(
        """
        select id, title, url, source_url, source_domain, source_provenance,
               coverage_evidence
        from articles where id = %s
        """,
        (int(article_id),),
    )
    if not article:
        raise LookupError("Article not found.")
    query = build_query(article.get("title") or "")
    result = summarize_results(article, _fetch(query), query)
    db.execute(
        "update articles set coverage_evidence = %s where id = %s",
        (Jsonb(result), int(article_id)),
    )
    return result
