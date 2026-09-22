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
from services.articles.publisher_identity import publisher_domain


STATUS_BROAD = "broad_coverage"
STATUS_SOME = "some_coverage"
STATUS_LOW = "no_coverage_found"
STATUS_NONE = "not_checked"
_TITLE_UP = re.compile(r"\b(approv(?:e|es|ed)|support(?:s|ed)?|increase[ds]?|rise[sn]?|rose|gain(?:s|ed)?|win[sn]?|won|allow(?:s|ed)?)\b", re.I)
_TITLE_DOWN = re.compile(r"\b(reject(?:s|ed)?|oppose[ds]?|decrease[ds]?|decline[ds]?|fall[sn]?|fell|lose[sn]?|lost|ban[sn]?|block(?:s|ed)?)\b", re.I)
_TITLE_NEGATION = re.compile(r"\b(no|not|never|without|didn't|doesn't|won't)\b", re.I)
class GdeltError(RuntimeError):
    """A safe, user-facing GDELT lookup failure."""


def normalize_domain(value) -> str | None:
    return publisher_domain(value)


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


def _title_direction(value: str) -> str:
    negated = bool(_TITLE_NEGATION.search(value))
    up, down = bool(_TITLE_UP.search(value)), bool(_TITLE_DOWN.search(value))
    if up and down:
        return "mixed"
    if negated and up:
        return "negative"
    if negated and down:
        return "positive"
    if up:
        return "positive"
    if down or negated:
        return "negative"
    return "neutral"


def _title_quantities(value: str) -> set[str]:
    return {token.replace(",", "").lower() for token in re.findall(r"\b\d[\d,.]*%?\b", str(value or ""))}


def _title_relationship(expected: str, candidate: str) -> str | None:
    expected_quantities, candidate_quantities = _title_quantities(expected), _title_quantities(candidate)
    if expected_quantities or candidate_quantities:
        if expected_quantities != candidate_quantities:
            return None
    expected_direction, candidate_direction = _title_direction(expected), _title_direction(candidate)
    if {expected_direction, candidate_direction} == {"positive", "negative"}:
        return "contradicting"
    if "mixed" in {expected_direction, candidate_direction}:
        return None
    return "supporting"


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
        article_title = article.get("title") or ""
        overlap = _title_overlap(article_title, title)
        if overlap < config.GDELT_MIN_TITLE_OVERLAP:
            continue
        relationship = _title_relationship(article_title, title)
        if relationship is None:
            continue
        candidate = {
            "domain": domain,
            "title": title,
            "url": url,
            "seen_at": raw.get("seendate"),
            "language": raw.get("language"),
            "source_country": raw.get("sourcecountry"),
            "title_overlap": round(overlap, 3),
            "relationship": relationship,
        }
        previous = matches_by_domain.get(domain)
        if previous is not None and previous["relationship"] != candidate["relationship"]:
            candidate["relationship"] = "conflicting"
        if previous is None or candidate["relationship"] == "conflicting" or candidate["title_overlap"] > previous["title_overlap"]:
            matches_by_domain[domain] = candidate

    matches = sorted(matches_by_domain.values(), key=lambda item: (-item["title_overlap"], item["domain"]))
    supporting_count = sum(match["relationship"] == "supporting" for match in matches)
    contradicting_count = sum(match["relationship"] == "contradicting" for match in matches)
    domain_count = len(matches)
    if domain_count:
        status = STATUS_SOME
        reason = "Related headlines were found. Their claims and source independence need review before reliability can be assessed."
    else:
        status = STATUS_NONE
        reason = "There is not enough matching coverage to assess this source."

    return {
        "status": status,
        "rules_version": "coverage-v2",
        "reason": reason,
        "query": query,
        "matching_domain_count": domain_count,
        "supporting_domain_count": supporting_count,
        "contradicting_domain_count": contradicting_count,
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
    if 'error' in payload or ('articles' in payload and not isinstance(payload['articles'], list)):
        raise GdeltError("The coverage service could not complete this assessment. Please try again later.")
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
