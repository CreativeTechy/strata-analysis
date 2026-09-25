"""Evidence links: the articles behind one dashboard number or chart selection.

Every figure on the intelligence dashboard (get_project_intelligence()) is a
count over one project's rows in one scope - a period window over the live
`articles` rows, or one analysis run's snapshots - bucketed by a dimension
(sentiment, platform, language, a demographic column, trust tier, emotion,
day). resolve_evidence() picks out exactly the rows that count covered, using
the same row source and the same bucketing functions, so the Articles page a
selection opens on lists the same articles the chart counted - not a
re-derivation that drifts from it (e.g. a run-scoped "negative" read off each
article's *latest* sentiment instead of what that run concluded).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from services.intelligence import intelligence
from services.intelligence.intelligence import (
    TONE_TO_EMOTION,
    article_date,
    classify_platform,
    compute_overall_tone,
    filter_rows_for_period,
    normalize_period,
)

# The query params a selection can carry, in the order they are applied.
# `sentiment` is also an ordinary Articles-page filter; inside an evidence
# scope it is resolved here instead, because a run-scoped sentiment has to be
# read off that run's snapshot rather than off the article row.
DIMENSIONS = ("sentiment", "platform", "language", "region", "gender", "age_range", "segment", "trust", "emotion", "date")

# Analysis fields a run's snapshot carries (see
# article_analyses.fetch_run_article_rows). Overlaid onto the article rows the
# Articles page lists in run scope, so a card shows what that run concluded -
# the thing the selection was counted on - rather than the latest analysis.
SNAPSHOT_FIELDS = (
    "summary", "sentiment", "writer_tone", "article_tone",
    "region", "gender", "age_range", "segment",
    "insight_json", "source_language", "relevance_score", "topics", "key_points",
)


@dataclass
class EvidenceMatch:
    article_ids: list[int]
    # {article_id: {field: value}} - only in run scope, see SNAPSHOT_FIELDS.
    snapshots: dict[int, dict] = field(default_factory=dict)


def _clean(value) -> str:
    return str(value or "").strip()


def _bucket_text(value) -> str:
    # Same bucketing as articles_analytics._demographic_sentiment_breakdown:
    # stripped, case preserved, missing -> "unknown".
    return _clean(value) or "unknown"


def _language(row) -> str:
    # Same as articles_analytics._source_language_counts.
    return _clean(row.get("source_language")).lower() or "unknown"


def _emotion(row) -> str | None:
    return TONE_TO_EMOTION.get(compute_overall_tone(row.get("article_tone"), row.get("writer_tone")))


def _day(row) -> str | None:
    date = article_date(row)
    return date.date().isoformat() if date else None


def _trust_tiers(rows: list[dict], project_id: int) -> dict[int, str]:
    from services.articles.articles_query import source_group_identity, trust_tier_by_source_key

    tier_by_key = trust_tier_by_source_key(rows, project_id=project_id)
    tiers = {}
    for row in rows:
        key = source_group_identity(row.get("url"), row.get("source"), row.get("source_url"))[0]
        tiers[row.get("id")] = tier_by_key.get(key, "unknown")
    return tiers


def normalize_filters(raw: dict) -> dict:
    """Drops blank values so "no selection" and "empty selection" can't differ."""
    return {name: _clean(raw.get(name)) for name in DIMENSIONS if _clean(raw.get(name))}


def resolve_evidence(project_id: int, period: str | None = None, run_id: str | None = None, filters: dict | None = None) -> EvidenceMatch:
    """The ids of the articles one dashboard selection counted.

    Scope mirrors get_project_intelligence(): a run_id wins over period (the
    dashboard's run tab replaces its date tabs rather than narrowing them).
    Unlike that function, a missing period means no date window rather than
    its 30-day default - a link that names no scope must not invent one.
    """
    filters = normalize_filters(filters or {})
    if run_id:
        rows = intelligence._fetch_project_rows(project_id, run_id=run_id)
    else:
        rows = intelligence._fetch_project_rows(project_id)
        if period:
            rows = filter_rows_for_period(rows, normalize_period(period))

    # Each check binds its wanted value as a default argument - a plain
    # closure over one reused local would compare every check against the
    # last filter's value.
    checks = []
    if "sentiment" in filters:
        checks.append(lambda row, wanted=filters["sentiment"].lower(): _clean(row.get("sentiment")).lower() == wanted)
    if "platform" in filters:
        checks.append(lambda row, wanted=filters["platform"].lower(): classify_platform(row).lower() == wanted)
    if "language" in filters:
        checks.append(lambda row, wanted=filters["language"].lower(): _language(row) == wanted)
    for column in ("region", "gender", "age_range", "segment"):
        if column in filters:
            checks.append(lambda row, column=column, wanted=filters[column]: _bucket_text(row.get(column)) == wanted)
    if "emotion" in filters:
        checks.append(lambda row, wanted=filters["emotion"].lower(): _emotion(row) == wanted)
    if "date" in filters:
        checks.append(lambda row, wanted=filters["date"][:10]: _day(row) == wanted)

    matched = [row for row in rows if all(check(row) for check in checks)]
    # Trust is resolved last and only over what survived the cheap checks - it
    # is the one dimension that needs a database lookup.
    if "trust" in filters and matched:
        wanted = filters["trust"].lower()
        tiers = _trust_tiers(matched, project_id)
        matched = [row for row in matched if tiers.get(row.get("id")) == wanted]

    ids = []
    snapshots = {}
    for row in matched:
        try:
            article_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        ids.append(article_id)
        if run_id:
            snapshots[article_id] = {name: row.get(name) for name in SNAPSHOT_FIELDS if name in row}
    return EvidenceMatch(article_ids=ids, snapshots=snapshots)


def overlay_snapshots(rows: list[dict], match: EvidenceMatch | None, run_id: str | None) -> list[dict]:
    """Replaces each listed row's analysis fields with its run snapshot, and
    marks which run they came from so the page can say so."""
    if not match or not run_id:
        return rows
    for row in rows:
        try:
            snapshot = match.snapshots.get(int(row.get("id")))
        except (TypeError, ValueError):
            snapshot = None
        if snapshot:
            row.update(snapshot)
            row["analysis_run_id"] = run_id
    return rows
