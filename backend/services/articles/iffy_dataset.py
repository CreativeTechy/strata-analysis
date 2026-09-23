"""A locally imported snapshot of Iffy.news' "Index of Unreliable Sources"
(CC BY 4.0, https://iffy.news/index/) - a second, wider seeded default for
source_trust.py's trust tiers, alongside the hand-curated
trusted_sources.TRUSTED_DOMAINS allowlist.

Iffy is a concern list built from Media Bias/Fact Check ratings: a match is
useful negative evidence ("this publisher has reported reliability
concerns"), and an absent domain is "not listed", never "verified reliable".
So this module only ever feeds a default *untrusted* tier - it must never be
read as a positive/trusted signal.

This module never contacts Iffy itself. scripts/import_iffy_dataset.py is
operator-run tooling that downloads the feed once and stores it here,
versioned (source_reliability_datasets/source_reliability_ratings -
migrations/0027_iffy_dataset.sql); the running app only ever reads the
locally imported copy, same offline-by-default posture as
trusted_sources.py, just wider and refreshable instead of hand-maintained.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import logging

import config
import db
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)

PROVIDER = "iffy"
PROVIDER_LABEL = "Iffy.news"
PROVIDER_PAGE = "https://iffy.news/index/"
PROVIDER_LICENSE = "CC BY 4.0"
DEFAULT_FEED_URL = (
    "https://opensheet.elk.sh/1ck1_FZC-97uDLIlvRJDTrGqBk0FuDe9yHkluROgpGS8/Iffy-news"
)


def active_dataset_metadata() -> dict | None:
    """Public provenance for the currently active import, or None if no
    dataset has ever been imported - what the Sources tab can show next to
    an Iffy-sourced default tier, and what the import script prints."""
    if not config.DATABASE_URL:
        return None
    try:
        row = db.fetch_one(
            """
            select version, source_url, license, record_count, imported_at
            from source_reliability_datasets
            where provider = %s and active = true
            order by imported_at desc
            limit 1
            """,
            (PROVIDER,),
        )
    except Exception:
        return None
    if not row:
        return None
    return {
        "provider": PROVIDER_LABEL,
        "version": row.get("version"),
        "source_url": row.get("source_url"),
        "license": row.get("license"),
        "record_count": int(row.get("record_count") or 0),
        "imported_at": row.get("imported_at"),
    }


@lru_cache(maxsize=1)
def _active_ratings() -> dict[str, dict]:
    """{domain: {publisher_name, factual_rating, credibility_rating,
    review_url}} for the currently active dataset. Cached for the process
    lifetime - import_records() clears this right after a new import
    activates, the only way the active dataset ever changes."""
    if not config.DATABASE_URL:
        return {}
    try:
        dataset = db.fetch_one(
            "select id from source_reliability_datasets where provider = %s and active = true "
            "order by imported_at desc limit 1",
            (PROVIDER,),
        )
        if not dataset:
            return {}
        rows = db.fetch_all(
            "select domain, publisher_name, factual_rating, credibility_rating, review_url "
            "from source_reliability_ratings where dataset_id = %s",
            (dataset["id"],),
        )
    except Exception:
        return {}
    return {row["domain"]: row for row in rows or [] if row.get("domain")}


def lookup(domain: str) -> dict | None:
    """Match `domain` or one of its parent domains against the active
    dataset - a subdomain of a listed domain inherits its publisher's
    rating, same subdomain-match behavior as trusted_sources.is_trusted_domain.
    None means "not listed", never a positive rating - see module docstring."""
    domain = (domain or "").strip().lower()
    if not domain:
        return None
    ratings = _active_ratings()
    if not ratings:
        return None
    labels = domain.split(".")
    for index in range(max(1, len(labels) - 1)):
        candidate = ".".join(labels[index:])
        if candidate in ratings:
            return ratings[candidate]
    return None


def clear_cache():
    _active_ratings.cache_clear()


def _clean_records(records: list[dict]) -> list[dict]:
    from services.articles.publisher_identity import publisher_domain

    cleaned = {}
    for raw in records:
        if not isinstance(raw, dict):
            continue
        domain = publisher_domain(raw.get("Domain") or raw.get("domain") or raw.get("URL"))
        if not domain:
            continue
        cleaned[domain] = {
            "domain": domain,
            "publisher_name": str(raw.get("Name") or raw.get("name") or "").strip() or None,
            "factual_rating": str(raw.get("MBFC Fact") or "").strip() or None,
            "credibility_rating": str(raw.get("MBFC cred") or "").strip() or None,
            "review_url": str(raw.get("Media Bias/Fact Check") or "").strip() or None,
            "raw_data": raw,
        }
    return [cleaned[key] for key in sorted(cleaned)]


def import_records(records: list[dict], *, source_url: str = DEFAULT_FEED_URL,
                    minimum_records: int = 100) -> dict:
    """Validate, version and activate an Iffy dataset - called only from
    scripts/import_iffy_dataset.py, never from the running app.

    `minimum_records` is a sanity floor, not a real minimum: a near-empty
    "dataset" (a truncated download, a format change upstream) must fail
    loudly here rather than silently blank out every existing untrusted
    default the next time a page loads.
    """
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
                (dataset_id, domain, publisher_name, factual_rating, credibility_rating, review_url, raw_data)
            values (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    dataset_id, row["domain"], row["publisher_name"],
                    row["factual_rating"], row["credibility_rating"], row["review_url"],
                    Jsonb(row["raw_data"]),
                )
                for row in cleaned
            ],
        )

    clear_cache()
    return {"provider": PROVIDER_LABEL, "version": version, "domains_imported": len(cleaned)}
