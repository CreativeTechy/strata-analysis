"""Competitors and the evidence attached to them.

A competitor here is never discovered or scraped: it is named by
document_analysis.py from the articles a study's uploaded documents were split
into, or entered by hand. There are therefore no channels/accounts to validate
and nothing to link into a crawler - a competitor is a name (plus aliases, and
optionally a website and country) that evidence is matched against, and
`competitor_findings` is what the analysis writes back.
"""

from __future__ import annotations

from urllib.parse import urlparse

from psycopg.types.json import Jsonb

import db
from embeddings import build_competitor_embedding_text, get_embedding
from services.competitors.countries import COUNTRIES, validate_countries

COMPETITOR_COLUMNS = """
    id, project_id, name, website, domain, description, country,
    operates_in_countries, aliases, size_tier, size_rank, size_signals,
    relevance_score, status, discovery_source, discovery_query,
    last_analyzed_at, created_at, updated_at
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

    row = db.fetch_one(
        f"""
        insert into competitors (project_id, {', '.join(fields)})
        values (%s, {', '.join(['%s'] * len(fields))})
        on conflict {conflict} do update set {assignments}
        returning {COMPETITOR_COLUMNS}
        """,
        (int(project_id), *[payload[field] for field in fields]),
    )
    if row:
        _persist_competitor_embedding(row)
    return row


def _persist_competitor_embedding(competitor: dict) -> None:
    """Keep the competitor's identity embedding (name + aliases + description)
    in step with every create/update, so semantic-similarity matching in
    competitor_analysis.py always has something current to compare articles
    against - not just the literal-name gate. Best-effort: an unavailable
    embedding model must not block saving the competitor itself.
    """
    text = build_competitor_embedding_text(competitor)
    if not text:
        return
    embedding = get_embedding(text)
    if not embedding:
        return
    db.execute(
        """
        update competitors
           set embedding_json = %s, embedding_model = %s,
               embedding_source = %s, embedded_at = %s
         where id = %s
        """,
        (
            Jsonb(embedding.get("embedding_json") or []),
            embedding.get("embedding_model"),
            embedding.get("embedding_source"),
            embedding.get("embedded_at"),
            int(competitor["id"]),
        ),
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


def competitor_overview(project_id: int) -> list[dict]:
    """Competitors with their finding counts, for the workspace list."""
    return db.fetch_all(
        f"""
        select {_prefixed(COMPETITOR_COLUMNS, 'c')},
               coalesce(fin.total, 0)::int      as finding_count,
               coalesce(fin.high, 0)::int       as high_impact_count,
               fin.latest_generated_at
        from competitors c
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


# --------------------------------------------------------------------------- #
# Studies - a competitor-mode project. Not "competitors" itself, but competitor_api.py's
# only other table access, so it lives here rather than in the route module.
# --------------------------------------------------------------------------- #
STUDY_COLUMNS = "id, name, mode, status, last_run_at, last_run_status"


def get_study(project_id: int) -> dict | None:
    return db.fetch_one(
        f"select {STUDY_COLUMNS} from projects where id = %s",
        (int(project_id),),
    )


def list_studies() -> list[dict]:
    """Competitor-mode projects with enough summary to render the index."""
    return db.fetch_all(
        """
        with latest_findings as (
            -- One row per competitor's *current* card, not per generation
            -- event: generate_finding() always inserts (never updates), so
            -- re-running analysis on the same competitor leaves its older
            -- findings in place as history rather than superseding them in
            -- place. Counting competitor_findings directly counted every
            -- one of those, so the number grew on every re-run even with
            -- the competitor set unchanged, and didn't match the study's
            -- own findings grid - which shows one card per competitor, the
            -- newest, excluding rejected ones.
            select distinct on (competitor_id)
                   project_id, competitor_id, impact_level, generated_at
            from competitor_findings
            where validation_status != 'rejected'
            order by competitor_id, generated_at desc
        )
        select p.id, p.name, p.status, p.mode, p.created_at, p.updated_at,
               p.last_run_at, p.last_run_status,
               bp.name as business_name, bp.website as business_website,
               bp.market, bp.industry,
               coalesce(c.tracked, 0)::int   as tracked_competitors,
               coalesce(c.suggested, 0)::int as suggested_competitors,
               coalesce(f.total, 0)::int     as finding_count,
               coalesce(f.high, 0)::int      as high_impact_count,
               f.latest_generated_at
        from projects p
        left join business_profiles bp on bp.project_id = p.id
        left join (
            select project_id,
                   count(*) filter (where status = 'tracked')   as tracked,
                   count(*) filter (where status = 'suggested') as suggested
            from competitors group by project_id
        ) c on c.project_id = p.id
        left join (
            select project_id, count(*) as total,
                   count(*) filter (where impact_level = 'high') as high,
                   max(generated_at) as latest_generated_at
            from latest_findings group by project_id
        ) f on f.project_id = p.id
        where p.mode = 'competitor'
        order by p.created_at desc
        """
    )


def create_study(name: str, status: str, description: str | None) -> dict | None:
    return db.fetch_one(
        """
        insert into projects (name, mode, status, description)
        values (%s, 'competitor', %s, %s)
        returning id, name, mode, status, created_at
        """,
        (name, status, description),
    )


def update_study(project_id: int, name: str, status: str, description: str | None) -> dict | None:
    return db.fetch_one(
        """
        update projects
           set name = %s, status = %s, description = %s, updated_at = now()
         where id = %s and mode = 'competitor'
        returning id, name, mode, status, description, created_at, updated_at
        """,
        (name, status, description, int(project_id)),
    )
