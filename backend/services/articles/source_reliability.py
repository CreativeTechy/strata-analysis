"""Publisher-level reliability signals backed by a local Iffy dataset.

Iffy is a list of publishers with reported reliability concerns.  A match is
useful negative evidence; the absence of a match is not a positive rating.
The ordinary analysis pipeline never contacts Iffy.  An operator explicitly
imports a dataset, after which article assessment is a local database lookup.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache
import hashlib
import json
import logging
from urllib.parse import urlsplit

import db
from psycopg.types.json import Jsonb


logger = logging.getLogger(__name__)

PROVIDER = "iffy"
PROVIDER_LABEL = "Iffy.news"
PROVIDER_PAGE = "https://iffy.news/index/"
PROVIDER_LICENSE = "CC BY 4.0"
DEFAULT_FEED_URL = (
    "https://opensheet.elk.sh/"
    "1ck1_FZC-97uDLIlvRJDTrGqBk0FuDe9yHkluROgpGS8/Iffy-news"
)

STATUS_CONCERN = "concern_reported"
STATUS_NOT_LISTED = "not_listed"
STATUS_NOT_ASSESSED = "not_assessed"
VALID_STATUSES = {STATUS_CONCERN, STATUS_NOT_LISTED, STATUS_NOT_ASSESSED}


def _timestamp_text(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def normalize_domain(value) -> str | None:
    """Return a comparable ASCII hostname from a URL or bare domain."""
    text = str(value or "").strip()
    if not text or text.lower().startswith("document://"):
        return None
    candidate = text if "://" in text else f"//{text}"
    try:
        parsed = urlsplit(candidate)
        hostname = (parsed.hostname or "").strip().lower().rstrip(".")
        if hostname.startswith("www."):
            hostname = hostname[4:]
        if not hostname or "." not in hostname or " " in hostname:
            return None
        return hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return None


def resolve_source_domain(article: dict) -> str | None:
    """Resolve the original publisher, never an internal document locator."""
    provenance = article.get("source_provenance")
    if isinstance(provenance, dict):
        domain = normalize_domain(provenance.get("original_url"))
        if domain:
            return domain
    for field in ("url", "source_url"):
        domain = normalize_domain(article.get(field))
        if domain:
            return domain
    return None


def match_rating(domain: str | None, ratings: dict[str, dict]) -> dict | None:
    """Match an exact publisher domain or one of its subdomains."""
    current = normalize_domain(domain)
    if not current:
        return None
    labels = current.split(".")
    for index in range(max(1, len(labels) - 1)):
        candidate = ".".join(labels[index:])
        if candidate in ratings:
            return ratings[candidate]
    return None


def assess(article: dict, dataset: dict | None, ratings: dict[str, dict]) -> dict:
    domain = resolve_source_domain(article)
    if not domain:
        return {
            "status": STATUS_NOT_ASSESSED,
            "domain": None,
            "reason": "No original publisher URL is available.",
            "provider": PROVIDER_LABEL,
            "reference_url": PROVIDER_PAGE,
            "dataset_version": dataset.get("version") if dataset else None,
            "details": {},
        }
    if not dataset:
        return {
            "status": STATUS_NOT_ASSESSED,
            "domain": domain,
            "reason": "The Iffy publisher dataset has not been imported.",
            "provider": PROVIDER_LABEL,
            "reference_url": PROVIDER_PAGE,
            "dataset_version": None,
            "details": {},
        }

    rating = match_rating(domain, ratings)
    if rating:
        matched_domain = rating["domain"]
        return {
            "status": STATUS_CONCERN,
            "domain": domain,
            "reason": f"Iffy reports reliability concerns for {matched_domain}.",
            "provider": PROVIDER_LABEL,
            "reference_url": rating.get("review_url") or PROVIDER_PAGE,
            "dataset_version": dataset["version"],
            "details": {
                "matched_domain": matched_domain,
                "publisher_name": rating.get("publisher_name"),
                "factual_rating": rating.get("factual_rating"),
                "credibility_rating": rating.get("credibility_rating"),
                "quality_score": rating.get("quality_score"),
                "provider_score": rating.get("provider_score"),
                "dataset_imported_at": _timestamp_text(dataset.get("imported_at")),
            },
        }
    return {
        "status": STATUS_NOT_LISTED,
        "domain": domain,
        "reason": "The publisher is not listed in the imported Iffy dataset.",
        "provider": PROVIDER_LABEL,
        "reference_url": PROVIDER_PAGE,
        "dataset_version": dataset["version"],
        "details": {"dataset_imported_at": _timestamp_text(dataset.get("imported_at"))},
    }


def _active_dataset() -> tuple[dict | None, dict[str, dict]]:
    try:
        dataset = db.fetch_one(
            """
            select id, provider, version, source_url, license, checksum,
                   record_count, imported_at
            from source_reliability_datasets
            where provider = %s and active = true
            order by imported_at desc
            limit 1
            """,
            (PROVIDER,),
        )
        if not dataset:
            return None, {}
        return dataset, _ratings_for_dataset(int(dataset["id"]))
    except Exception:
        return None, {}


def get_active_dataset_metadata() -> dict | None:
    """Return public provenance for the local dataset without loading ratings."""
    dataset, _ = _active_dataset()
    if not dataset:
        return None
    return {
        "provider": PROVIDER_LABEL,
        "version": dataset.get("version"),
        "source_url": dataset.get("source_url"),
        "license": dataset.get("license"),
        "record_count": int(dataset.get("record_count") or 0),
        "imported_at": dataset.get("imported_at"),
    }


@lru_cache(maxsize=4)
def _ratings_for_dataset(dataset_id: int) -> dict[str, dict]:
    rows = db.fetch_all(
        """
        select domain, publisher_name, factual_rating, credibility_rating,
               quality_score, provider_score, review_url, raw_data
        from source_reliability_ratings
        where dataset_id = %s
        """,
        (int(dataset_id),),
    )
    normalized = {}
    for value in rows or []:
        row = dict(value)
        row["quality_score"] = _number(row.get("quality_score"))
        row["provider_score"] = _number(row.get("provider_score"))
        normalized[row["domain"]] = row
    return normalized


_UPDATE_SQL = """
    update articles
       set source_domain = %s,
           source_reliability_status = %s,
           source_reliability_reason = %s,
           source_reliability_provider = %s,
           source_reliability_reference_url = %s,
           source_reliability_dataset_version = %s,
           source_reliability_details = %s,
           source_reliability_assessed_at = now()
     where id = %s
"""


def _assessment_params(article_id: int, result: dict) -> tuple:
    return (
        result.get("domain"),
        result["status"],
        result["reason"],
        result["provider"],
        result["reference_url"],
        result.get("dataset_version"),
        Jsonb(result.get("details") or {}),
        int(article_id),
    )


def _preserve_article_level_signals(article: dict, result: dict) -> dict:
    """Keep separately gathered evidence when refreshing the Iffy signal."""
    existing = article.get("source_reliability_details")
    gdelt = existing.get("gdelt_coverage") if isinstance(existing, dict) else None
    if gdelt:
        result = {**result, "details": {**(result.get("details") or {}), "gdelt_coverage": gdelt}}
    return result


def assess_article(article_id: int) -> dict | None:
    """Assess one stored article. Failure never blocks article persistence."""
    try:
        article = db.fetch_one(
            "select id, url, source_url, source_provenance, source_reliability_details from articles where id = %s",
            (int(article_id),),
        )
        if not article:
            return None
        dataset, ratings = _active_dataset()
        result = _preserve_article_level_signals(article, assess(article, dataset, ratings))
        db.execute(_UPDATE_SQL, _assessment_params(article["id"], result))
        return result
    except Exception as exc:
        logger.warning("Source reliability assessment skipped for article %s: %s", article_id, exc)
        return None


def assess_all_articles() -> dict:
    """Reassess every article against the currently active local dataset."""
    rows = db.fetch_all(
        "select id, url, source_url, source_provenance, source_reliability_details from articles order by id"
    ) or []
    dataset, ratings = _active_dataset()
    counts = Counter()
    with db.transaction() as cur:
        for article in rows:
            result = _preserve_article_level_signals(article, assess(article, dataset, ratings))
            cur.execute(_UPDATE_SQL, _assessment_params(article["id"], result))
            counts[result["status"]] += 1
    return {"articles_assessed": len(rows), "counts": dict(counts)}


def _number(value):
    try:
        return float(value) if str(value or "").strip() else None
    except (TypeError, ValueError):
        return None


def _clean_records(records: list[dict]) -> list[dict]:
    cleaned = {}
    for raw in records:
        if not isinstance(raw, dict):
            continue
        domain = normalize_domain(raw.get("Domain") or raw.get("domain") or raw.get("URL"))
        if not domain:
            continue
        cleaned[domain] = {
            "domain": domain,
            "publisher_name": str(raw.get("Name") or raw.get("name") or "").strip() or None,
            "factual_rating": str(raw.get("MBFC Fact") or "").strip() or None,
            "credibility_rating": str(raw.get("MBFC cred") or "").strip() or None,
            "quality_score": _number(raw.get("Quality")),
            "provider_score": _number(raw.get("Score")),
            "review_url": str(raw.get("Media Bias/Fact Check") or "").strip() or None,
            "raw_data": raw,
        }
    return [cleaned[key] for key in sorted(cleaned)]


def import_iffy_records(records: list[dict], *, source_url: str = DEFAULT_FEED_URL,
                        minimum_records: int = 100) -> dict:
    """Validate, version and activate an Iffy dataset, then reassess articles."""
    cleaned = _clean_records(records)
    if len(cleaned) < minimum_records:
        raise ValueError(
            f"Iffy dataset contains {len(cleaned)} valid domains; expected at least {minimum_records}."
        )
    canonical = json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    version = f"iffy-{checksum[:12]}"

    with db.transaction() as cur:
        cur.execute(
            "update source_reliability_datasets set active = false where provider = %s",
            (PROVIDER,),
        )
        cur.execute(
            """
            insert into source_reliability_datasets
                (provider, version, source_url, license, checksum, record_count, active)
            values (%s, %s, %s, %s, %s, %s, true)
            on conflict (provider, version) do update
               set source_url = excluded.source_url,
                   license = excluded.license,
                   checksum = excluded.checksum,
                   record_count = excluded.record_count,
                   imported_at = now(),
                   active = true
            returning id
            """,
            (PROVIDER, version, source_url, PROVIDER_LICENSE, checksum, len(cleaned)),
        )
        dataset_id = cur.fetchone()["id"]
        cur.execute("delete from source_reliability_ratings where dataset_id = %s", (dataset_id,))
        cur.executemany(
            """
            insert into source_reliability_ratings
                (dataset_id, domain, publisher_name, factual_rating,
                 credibility_rating, quality_score, provider_score, review_url, raw_data)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    dataset_id, row["domain"], row["publisher_name"], row["factual_rating"],
                    row["credibility_rating"], row["quality_score"], row["provider_score"],
                    row["review_url"], Jsonb(row["raw_data"]),
                )
                for row in cleaned
            ],
        )

    _ratings_for_dataset.cache_clear()
    assessment = assess_all_articles()
    return {
        "provider": PROVIDER_LABEL,
        "version": version,
        "domains_imported": len(cleaned),
        **assessment,
    }
