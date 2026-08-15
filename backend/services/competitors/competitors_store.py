"""Competitors, their accounts, and the link into the existing scrape machinery.

The important design choice here: a validated competitor account becomes a row in
`sources` joined to the project through `project_sources`. That means competitor
scraping is driven by the scraper, pipeline_runs, cancel support and
`projects.repeat_*` scheduler that already exist — there is no second pipeline to
build, schedule, or debug.

Only `valid` accounts are ever linked. A guessed handle that turns out to belong
to someone else would otherwise pull a stranger's activity into a competitor
report, and reports here are read as input to business decisions.
"""

from __future__ import annotations

from urllib.parse import urlparse

from psycopg.types.json import Jsonb

import db
from services.competitors.countries import COUNTRIES, validate_countries
from services.sources.sources_store import _derive_reddit_url, _derive_telegram_url, _derive_term_url

COMPETITOR_COLUMNS = """
    id, project_id, name, website, domain, description, country,
    operates_in_countries, aliases, size_tier, size_rank, size_signals,
    relevance_score, status, discovery_source, discovery_query,
    last_scraped_at, last_analyzed_at, created_at, updated_at
"""

MAX_ALIASES = 12
MAX_ALIAS_LENGTH = 80


def clean_aliases(value) -> list[str]:
    """Normalize user-supplied alternate names.

    Accepts a list or a comma-separated string, since the API takes both. Very
    short strings are dropped: a one- or two-character alias matches so much
    text that it cannot identify a company, and unlike the derived names these
    are never re-checked against a generic-word list - an alias here is trusted
    precisely because a human chose it.
    """
    if isinstance(value, str):
        candidates = value.split(",")
    elif isinstance(value, (list, tuple)):
        candidates = value
    else:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        alias = str(item or "").strip()[:MAX_ALIAS_LENGTH]
        if len(alias) < 3 or alias.casefold() in seen:
            continue
        seen.add(alias.casefold())
        cleaned.append(alias)
    return cleaned[:MAX_ALIASES]

ACCOUNT_COLUMNS = """
    id, competitor_id, platform, handle, url, confidence,
    validation_status, validation_reason, source_id, created_at, updated_at
"""

# Maps an account platform onto the `sources.source_type` vocabulary the scraper
# already understands, so no scraper changes are needed. The first block is the
# manual-entry/discovery vocabulary shared with the project wizard
# (dashboard SOURCE_KIND_OPTIONS / backend config.KNOWN_SOURCE_TYPES); the second
# block is legacy platform values from before source types were unified, kept so
# competitor_accounts rows created under the old vocabulary still resolve.
PLATFORM_SOURCE_TYPE = {
    "web": "web",
    "rss": "rss",
    "social": "social",
    "hashtag": "hashtag",
    "keyword": "keyword",
    "username": "username",
    "reddit": "reddit",
    "telegram": "telegram",
    "website": "web",
    "blog": "rss",
    "news": "web",
    "x": "social",
    "linkedin": "social",
    "facebook": "social",
    "instagram": "social",
    "youtube": "social",
}

# Platforms whose "url" is derived from a bare name/handle rather than typed in
# directly — mirrors services/sources/sources_store.py's own term/reddit/telegram
# derivation, reused here so manually-added competitor sources go through the
# same URL-shaping logic as the general sources API.
TERM_PLATFORMS = {"hashtag", "keyword", "username"}


def resolve_account_url(platform: str, url: str, handle: str) -> str | None:
    """The real URL to store for a manually-entered competitor source.

    Term-type platforms and reddit/telegram accept a bare name/handle instead of
    a URL; everything else still requires a plausible URL via
    normalize_source_url.
    """
    term = (handle or "").strip()
    if platform in TERM_PLATFORMS:
        return _derive_term_url(platform, term) or None
    if platform == "reddit":
        return _derive_reddit_url(url or term) or None
    if platform == "telegram":
        return _derive_telegram_url(url or term) or None
    return normalize_source_url(url)


def _domain(url: str) -> str:
    host = urlparse(str(url or "").strip()).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def normalize_source_url(url: str) -> str | None:
    """Shape-check a manually entered source URL, defaulting to https://.

    No network call - this only rejects input that could not possibly be a
    URL (no dotted host), so a bad manual entry is caught before anything is
    written rather than saved as an unreachable source.
    """
    url = str(url or "").strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    netloc = urlparse(url).netloc.lower()
    if not netloc or "." not in netloc:
        return None
    return url


def _columns(spec: str) -> list[str]:
    """Column names from one of the multi-line SELECT specs above."""
    return [name.strip() for name in spec.replace("\n", " ").split(",") if name.strip()]


def _prefixed(spec: str, alias: str) -> str:
    """`id, name` -> `a.id, a.name`, for queries that join."""
    return ", ".join(f"{alias}.{name}" for name in _columns(spec))


# --------------------------------------------------------------------------- #
# Competitors
# --------------------------------------------------------------------------- #
def list_competitors(project_id: int, status: str | None = None) -> list[dict]:
    """Competitors for a project, largest first. Unranked rows sort last."""
    clauses = ["project_id = %s"]
    params: list = [int(project_id)]
    if status:
        clauses.append("status = %s")
        params.append(status)
    return db.fetch_all(
        f"""
        select {COMPETITOR_COLUMNS}
        from competitors
        where {' and '.join(clauses)}
        order by size_rank nulls last, lower(name)
        """,
        tuple(params),
    )


def get_competitor(competitor_id: int) -> dict | None:
    return db.fetch_one(
        f"select {COMPETITOR_COLUMNS} from competitors where id = %s",
        (int(competitor_id),),
    )


def upsert_competitor(project_id: int, values: dict) -> dict | None:
    """Create or update a competitor, keyed on domain (or name when there is none).

    Two discovery passes finding the same company must converge on one row, which
    is why the conflict targets are the partial unique indexes from migration 0004.
    """
    name = str(values.get("name") or "").strip()
    if not name:
        return None

    website = str(values.get("website") or "").strip() or None
    domain = str(values.get("domain") or "").strip().lower() or (_domain(website) if website else None) or None
    raw_country = str(values.get("country") or "").strip().upper()
    country = raw_country if raw_country in COUNTRIES else None

    payload = {
        "name": name,
        "website": website,
        "domain": domain,
        "description": str(values.get("description") or "").strip() or None,
        "country": country,
        "operates_in_countries": Jsonb(validate_countries(values.get("operates_in_countries"))),
        "aliases": Jsonb(clean_aliases(values.get("aliases"))),
        "size_tier": str(values.get("size_tier") or "unknown").strip().lower(),
        "size_rank": values.get("size_rank"),
        "size_signals": Jsonb(values.get("size_signals") or {}),
        "relevance_score": values.get("relevance_score"),
        "status": str(values.get("status") or "suggested").strip().lower(),
        "discovery_source": str(values.get("discovery_source") or "ai").strip().lower(),
        "discovery_query": str(values.get("discovery_query") or "").strip() or None,
    }

    fields = list(payload)

    # An update must never destroy what a previous pass established. Discovery
    # runs more than once and manual edits arrive partial, so a call that omits
    # size_tier/size_rank/description would otherwise reset a ranked, described
    # competitor to "unknown" with no rank — silently reshuffling the workspace.
    # Each field below states what "no new information" looks like for it.
    KEEP_IF_ABSENT = (
        "website", "domain", "description", "country", "size_rank",
        "relevance_score", "discovery_query",
    )
    assignments_by_field = {
        # The user's decision to track outranks a later model suggestion.
        "status": "status = case when competitors.status = 'tracked' "
                  "then competitors.status else excluded.status end",
        # A human typed this competitor in themselves; a later AI pass that
        # happens to match the same domain/name must not relabel it as its own.
        "discovery_source": "discovery_source = case when competitors.discovery_source = 'manual' "
                            "then competitors.discovery_source else excluded.discovery_source end",
        # 'unknown' is the absence of a judgement, not a judgement of 'unknown'.
        "size_tier": "size_tier = case when excluded.size_tier = 'unknown' "
                     "then competitors.size_tier else excluded.size_tier end",
        # An empty object carries no signals; keep whatever we already knew.
        "size_signals": "size_signals = case when excluded.size_signals = '{}'::jsonb "
                        "then competitors.size_signals else excluded.size_signals end",
        # An empty list carries no new "where they compete with us" info.
        "operates_in_countries": "operates_in_countries = case when excluded.operates_in_countries = '[]'::jsonb "
                                 "then competitors.operates_in_countries else excluded.operates_in_countries end",
        # Same rule: a discovery pass that knows no alternate names must not
        # wipe the ones a human typed in to make this competitor matchable.
        "aliases": "aliases = case when excluded.aliases = '[]'::jsonb "
                   "then competitors.aliases else excluded.aliases end",
    }
    assignments = ", ".join(
        assignments_by_field.get(
            field,
            f"{field} = coalesce(excluded.{field}, competitors.{field})"
            if field in KEEP_IF_ABSENT
            else f"{field} = excluded.{field}",
        )
        for field in fields
    )
    conflict = "(project_id, domain) where domain is not null" if domain else "(project_id, lower(name)) where domain is null"

    return db.fetch_one(
        f"""
        insert into competitors (project_id, {', '.join(fields)})
        values (%s, {', '.join(['%s'] * len(fields))})
        on conflict {conflict} do update set {assignments}
        returning {COMPETITOR_COLUMNS}
        """,
        (int(project_id), *[payload[field] for field in fields]),
    )


def set_competitor_status(competitor_id: int, status: str) -> dict | None:
    if status not in {"suggested", "tracked", "ignored"}:
        return None
    return db.fetch_one(
        f"update competitors set status = %s where id = %s returning {COMPETITOR_COLUMNS}",
        (status, int(competitor_id)),
    )


def delete_competitor(competitor_id: int) -> bool:
    db.execute("delete from competitors where id = %s", (int(competitor_id),))
    return True


def rerank_competitors(project_id: int) -> None:
    """Renumber `size_rank` to be dense and gap-free, largest tier first."""
    tier_order = "case size_tier when 'enterprise' then 0 when 'mid_market' then 1 " \
                 "when 'smb' then 2 when 'startup' then 3 else 4 end"
    db.execute(
        f"""
        with ordered as (
            select id, row_number() over (
                order by {tier_order}, size_rank nulls last, lower(name)
            ) as rank
            from competitors
            where project_id = %s
        )
        update competitors c set size_rank = ordered.rank
        from ordered where ordered.id = c.id and
              (c.size_rank is distinct from ordered.rank)
        """,
        (int(project_id),),
    )


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
def list_accounts(competitor_id: int) -> list[dict]:
    return db.fetch_all(
        f"""
        select {ACCOUNT_COLUMNS} from competitor_accounts
        where competitor_id = %s
        order by (validation_status = 'valid') desc, confidence desc nulls last, platform
        """,
        (int(competitor_id),),
    )


def list_accounts_for_project(project_id: int) -> list[dict]:
    return db.fetch_all(
        f"""
        select {_prefixed(ACCOUNT_COLUMNS, 'a')}, c.name as competitor_name
        from competitor_accounts a
        join competitors c on c.id = a.competitor_id
        where c.project_id = %s
        order by c.size_rank nulls last, a.platform
        """,
        (int(project_id),),
    )


def upsert_account(competitor_id: int, values: dict) -> dict | None:
    platform = str(values.get("platform") or "").strip().lower()
    handle_input = str(values.get("handle") or "").strip().lstrip("@")
    url = resolve_account_url(platform, values.get("url"), handle_input)
    if not url or not platform:
        return None

    payload = {
        "platform": platform,
        "handle": handle_input or None,
        "url": url,
        "confidence": values.get("confidence"),
        "validation_status": str(values.get("validation_status") or "pending").strip().lower(),
        "validation_reason": str(values.get("validation_reason") or "").strip() or None,
    }
    fields = list(payload)
    # `url` is part of the conflict key, so re-asserting it in the update is
    # redundant; excluding it also keeps the original casing stable. A human
    # decision (valid or rejected) must not be reset back to pending by a
    # later automated pass finding the same URL.
    assignments_by_field = {
        "validation_status": "validation_status = case "
                             "when competitor_accounts.validation_status <> 'pending' "
                             "then competitor_accounts.validation_status else excluded.validation_status end",
    }
    assignments = ", ".join(
        assignments_by_field.get(field, f"{field} = excluded.{field}")
        for field in fields if field != "url"
    )

    row = db.fetch_one(
        f"""
        insert into competitor_accounts (competitor_id, {', '.join(fields)})
        values (%s, {', '.join(['%s'] * len(fields))})
        on conflict (competitor_id, platform, lower(url)) do update set {assignments}
        returning {ACCOUNT_COLUMNS}
        """,
        (int(competitor_id), *[payload[field] for field in fields]),
    )
    if not row:
        return None

    # A manually-created account can arrive already `valid` - that must link
    # into `sources` immediately, not only when validated later via the
    # dedicated confirm/reject endpoint.
    if row["validation_status"] == "valid" and not row.get("source_id"):
        if link_account_as_source(row):
            row = db.fetch_one(f"select {ACCOUNT_COLUMNS} from competitor_accounts where id = %s", (row["id"],))
    return row


def set_account_validation(account_id: int, status: str, reason: str = "") -> dict | None:
    """Validate or reject an account. Validating links it in as a scrape source."""
    if status not in {"pending", "valid", "rejected"}:
        return None

    row = db.fetch_one(
        f"""
        update competitor_accounts
           set validation_status = %s, validation_reason = %s
         where id = %s
        returning {ACCOUNT_COLUMNS}
        """,
        (status, reason.strip() or None, int(account_id)),
    )
    if not row:
        return None

    if status == "valid":
        link_account_as_source(row)
    elif status == "rejected":
        unlink_account_source(row)
    return db.fetch_one(f"select {ACCOUNT_COLUMNS} from competitor_accounts where id = %s", (int(account_id),))


def delete_account(account_id: int) -> bool:
    row = db.fetch_one("select id, source_id from competitor_accounts where id = %s", (int(account_id),))
    if row:
        unlink_account_source(row)
    db.execute("delete from competitor_accounts where id = %s", (int(account_id),))
    return True


# --------------------------------------------------------------------------- #
# Bridge into `sources` / `project_sources`
# --------------------------------------------------------------------------- #
def link_account_as_source(account: dict) -> int | None:
    """Register a validated account as a scrape source attached to the project.

    Reuses the existing sources table so the normal pipeline and the existing
    scheduler pick it up with no competitor-specific plumbing.
    """
    url = str(account.get("url") or "").strip()
    if not url:
        return None

    competitor = db.fetch_one(
        "select c.id, c.project_id, c.name from competitors c where c.id = %s",
        (int(account["competitor_id"]),),
    )
    if not competitor:
        return None

    platform = str(account.get("platform") or "news").lower()
    source_type = PLATFORM_SOURCE_TYPE.get(platform, "web")
    handle = str(account.get("handle") or "").strip()
    label = handle if platform == "keyword" and handle else f"{competitor['name']} - {platform}"

    source = db.fetch_one(
        """
        insert into sources (url, name, enabled, source_type)
        values (%s, %s, true, %s)
        on conflict (url) do update set name = excluded.name,
                                        source_type = excluded.source_type,
                                        enabled = true
        returning id
        """,
        (url, label, source_type),
    )
    if not source:
        return None

    source_id = int(source["id"])
    db.execute(
        """
        insert into project_sources (project_id, source_id)
        values (%s, %s)
        on conflict (project_id, source_id) do nothing
        """,
        (int(competitor["project_id"]), source_id),
    )
    db.execute(
        "update competitor_accounts set source_id = %s where id = %s",
        (source_id, int(account["id"])),
    )
    return source_id


def unlink_account_source(account: dict) -> None:
    """Detach a rejected account's source from the project.

    The `sources` row itself is left alone — another project may legitimately be
    scraping the same URL, and deleting it would cascade away its articles.
    """
    source_id = account.get("source_id")
    if not source_id:
        return
    competitor = db.fetch_one(
        "select project_id from competitors where id = %s", (int(account["competitor_id"]),)
    )
    if competitor:
        db.execute(
            "delete from project_sources where project_id = %s and source_id = %s",
            (int(competitor["project_id"]), int(source_id)),
        )
    db.execute("update competitor_accounts set source_id = null where id = %s", (int(account["id"]),))


def sync_project_sources(project_id: int) -> dict:
    """Make `project_sources` match the currently-valid accounts. Returns counts."""
    accounts = db.fetch_all(
        """
        select a.id, a.competitor_id, a.platform, a.url, a.validation_status, a.source_id
        from competitor_accounts a
        join competitors c on c.id = a.competitor_id
        where c.project_id = %s and c.status = 'tracked'
        """,
        (int(project_id),),
    )
    linked = unlinked = 0
    for account in accounts:
        if account["validation_status"] == "valid":
            if link_account_as_source(account):
                linked += 1
        elif account["source_id"]:
            unlink_account_source(account)
            unlinked += 1
    return {"linked": linked, "unlinked": unlinked}


def competitor_overview(project_id: int) -> list[dict]:
    """Competitors with their account and finding counts, for the workspace list."""
    return db.fetch_all(
        f"""
        select {_prefixed(COMPETITOR_COLUMNS, 'c')},
               coalesce(acc.total, 0)::int      as account_count,
               coalesce(acc.valid, 0)::int      as valid_account_count,
               coalesce(acc.pending, 0)::int    as pending_account_count,
               coalesce(fin.total, 0)::int      as finding_count,
               coalesce(fin.high, 0)::int       as high_impact_count,
               fin.latest_generated_at
        from competitors c
        left join (
            select competitor_id,
                   count(*) as total,
                   count(*) filter (where validation_status = 'valid') as valid,
                   count(*) filter (where validation_status = 'pending') as pending
            from competitor_accounts group by competitor_id
        ) acc on acc.competitor_id = c.id
        left join (
            select competitor_id,
                   count(*) as total,
                   count(*) filter (where impact_level = 'high') as high,
                   max(generated_at) as latest_generated_at
            from competitor_findings group by competitor_id
        ) fin on fin.competitor_id = c.id
        where c.project_id = %s
        order by c.size_rank nulls last, lower(c.name)
        """,
        (int(project_id),),
    )
