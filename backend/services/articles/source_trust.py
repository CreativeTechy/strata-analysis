"""Operator-set trust tier for a project's sources - the Sources tab's own
tier control (dashboard/src/components/SourcesPage.jsx). There is no separate
"Sources" management page for this: the trust tier is attached to and edited
from the exact same source groups list_project_sources() already computes.

Fully offline, by design - see migrations/0026_source_trust.sql's own note on
the GDELT-based "source reliability" feature this fork already reverted once
(f72fb52) for calling out to a network reputation feed. A tier comes from one
of three places, resolved in this order:

  1. An operator override recorded in `source_trust` (keyed on the same
     `real:<host>` / `document:<source_url>` string list_project_sources()
     groups by).
  2. A seeded default: a "real" source whose host is on the hand-curated
     trusted_sources.TRUSTED_DOMAINS allowlist starts 'trusted'.
  3. A second, wider seeded default: a "real" source whose host is in the
     locally imported Iffy.news concern dataset (iffy_dataset.py) starts
     'untrusted' - a concern list, so a *miss* here still falls through to
     'unknown', never 'trusted' (absence of a listing is not a positive
     rating). Everything else - including every "document" source, since an
     uploaded file has no publisher identity of its own - starts 'unknown'.

'unknown' (not yet assessed) is kept distinct from 'untrusted' (assessed and
rejected) throughout, including as an operator-settable value (a deliberate
"return to unassessed", same as evidence_provenance_reviews' own 'unassessed'
status) - collapsing the two is exactly what made the older boolean
`articles.verified` column (see store.py) useless as a trust signal.

Deliberately display-only for now: a trust tier does not change sentiment
aggregates, evidence strength, or anything else analysis produces. See
CLAUDE.md/this feature's own plan for why that is a later, separate decision.
"""
from __future__ import annotations

import db
from services.articles import iffy_dataset
from trusted_sources import is_trusted_domain

TIERS = ("trusted", "mixed", "untrusted", "unknown")
SOURCE_TYPES = ("real", "document")


def _default_tier(source_type: str, label: str) -> tuple[str, str | None, str | None]:
    """(tier, reason, set_by) for a source with no recorded operator
    override. `reason`/`set_by` are None for the plain allowlist match (there
    is nothing to say beyond "it's on our curated list"); the Iffy match
    gets a real reason/attribution since it names an external, checkable
    source for the concern."""
    if source_type != "real":
        return "unknown", None, None
    if is_trusted_domain(f"https://{label}"):
        return "trusted", None, None
    concern = iffy_dataset.lookup(label)
    if concern:
        ratings = " / ".join(filter(None, [concern.get("factual_rating"), concern.get("credibility_rating")]))
        reason = f"{iffy_dataset.PROVIDER_LABEL} reports reliability concerns for this publisher"
        reason += f" (MBFC rating: {ratings})." if ratings else "."
        return "untrusted", reason, iffy_dataset.PROVIDER_LABEL
    return "unknown", None, None


def _redact_cross_project_override(override: dict, viewer_project_id) -> dict:
    """An operator override's `reason`/`set_by_name` can name specifics from
    the project it was made in ("flagged for the Acme engagement") - fine
    for that project's own viewers, not for a second project that happens to
    cite the same "real:<host>" and can otherwise see it purely because the
    tier itself is intentionally global (see migrations/0026 and 0028's own
    notes). A "document:" override carries no such risk - its key already
    embeds one project's own document id, so only that project's
    list_project_sources() ever computes it - and a legacy row with no
    recorded project_id (saved before 0028) is treated as same-project
    rather than newly hiding something that was already visible."""
    if override.get("source_type") != "real":
        return override
    override_project_id = override.get("project_id")
    if override_project_id is None or viewer_project_id is None or override_project_id == viewer_project_id:
        return override
    redacted = dict(override)
    redacted["reason"] = None
    redacted["set_by_name"] = None
    return redacted


def resolve_many(sources: list[dict], project_id=None) -> dict[str, dict]:
    """{key: {tier, reason, set_by, updated_at, is_default}} for every group
    in `sources` (each a dict carrying at least the key/type/label
    list_project_sources()'s own groups already have).

    `project_id` is the project whose Sources tab is being rendered - used
    only to redact a cross-project "real:" override's reason/set_by (see
    _redact_cross_project_override()), never to filter which sources get a
    tier at all: the tier itself stays visible regardless, by design.

    One query for the whole page rather than one per source - the same
    "small enough to stay cheap" reasoning list_project_sources() itself
    documents, since this is only ever called with that function's already
    paginated groups.
    """
    keys = [source["key"] for source in sources if source.get("key")]
    if not keys:
        return {}
    try:
        rows = db.fetch_all(
            "select source_key, source_type, tier, reason, set_by_name, updated_at, project_id "
            "from source_trust where source_key = any(%s)",
            (keys,),
        )
    except Exception:
        rows = []
    overrides = {row.get("source_key"): row for row in rows or [] if row.get("source_key")}

    result = {}
    for source in sources:
        key = source.get("key")
        if not key:
            continue
        override = overrides.get(key)
        if override:
            override = _redact_cross_project_override(override, project_id)
            result[key] = {
                "tier": override.get("tier"),
                "reason": override.get("reason"),
                "set_by": override.get("set_by_name"),
                "updated_at": override.get("updated_at"),
                "is_default": False,
            }
        else:
            tier, reason, set_by = _default_tier(source.get("type"), source.get("label") or "")
            result[key] = {
                "tier": tier,
                "reason": reason,
                "set_by": set_by,
                "updated_at": None,
                "is_default": True,
            }
    return result


def set_tier(source_key: str, source_type: str, tier: str, reason: str, user: dict, project_id=None) -> dict:
    """Record an operator's trust-tier decision for one source group.

    Requires a reason for every tier, including 'unknown' (a deliberate
    "return to unassessed", not the same as never having been reviewed) -
    same mandatory-reason rule review_provenance() (evidence workspace)
    already enforces, for the same audit-trail reason.

    `project_id` is the project the operator was looking at when they made
    this call (main.py's route always supplies it) - resolve_many() uses it
    to redact this override's reason/set_by for a different project's
    viewer. The audit row and the current-tier row are written in the same
    transaction so the append-only trail can never end up recording a
    change that the live table itself doesn't reflect.
    """
    source_key = str(source_key or "").strip()
    source_type = str(source_type or "").strip()
    tier = str(tier or "").strip()
    reason = str(reason or "").strip()[:1000]
    if not source_key:
        raise ValueError("A source key is required.")
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"Invalid source type: {source_type!r}")
    if tier not in TIERS:
        raise ValueError(f"Invalid trust tier: {tier!r}")
    if not reason:
        raise ValueError("A reason is required to set a source's trust tier.")

    set_by_name = (user or {}).get("username") or (user or {}).get("email")
    set_by_user_id = (user or {}).get("id")

    with db.transaction() as cur:
        cur.execute(
            """insert into source_trust_reviews
               (source_key, source_type, tier, reason, set_by_user_id, set_by_name, project_id)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (source_key, source_type, tier, reason, set_by_user_id, set_by_name, project_id),
        )
        cur.execute(
            """
            insert into source_trust (source_key, source_type, tier, reason, set_by_user_id, set_by_name, project_id)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (source_key) do update set
                source_type = excluded.source_type,
                tier = excluded.tier,
                reason = excluded.reason,
                set_by_user_id = excluded.set_by_user_id,
                set_by_name = excluded.set_by_name,
                project_id = excluded.project_id,
                updated_at = now()
            returning source_key, source_type, tier, reason, set_by_name, updated_at
            """,
            (source_key, source_type, tier, reason, set_by_user_id, set_by_name, project_id),
        )
        return cur.fetchone()
