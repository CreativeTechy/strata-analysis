"""Per-run analysis snapshots - what a given analysis run concluded about a
given article.

Why this exists
---------------
Analysis output lives on the `articles` row, one set of columns per article, so
re-analyzing an article overwrites it. In the crawler this was forked from that
was fine: a run *discovered* articles and analyzed each one once, so
`articles.pipeline_run_id` ("which run first saved this") partitioned runs
cleanly. Here a run re-analyzes articles that already exist, so without a
snapshot the second run over a project tags no articles at all while silently
overwriting the first run's conclusions - every run collapses into "the latest
analysis" and nothing can be compared against anything.

One row per (run_id, article_id) fixes that. `articles` still holds the latest
analysis, so every non-run-scoped reader is unaffected; run-scoped readers
(the dashboard's run picker, the per-run report) read here instead.

How a snapshot is written
-------------------------
`INSERT ... SELECT` straight from the `articles` row the run just wrote, rather
than from the in-memory analysis dict. The analysis dict uses the pipeline's own
key names (`overall_sentiment`, `topic`, ...) which `store._row()` maps onto
column names; re-implementing that mapping here would be a second copy to keep
in sync, and it would drift the first time a stage renames an output. Reading
the persisted row means the snapshot is by construction exactly what was saved.

That also fixes the ordering constraint for free: `segment` is not written by
the article upsert at all - it is derived from people-opinion votes in a follow-up
UPDATE - so a snapshot built from the dict would always miss it. Call this after
save_articles() has returned and both writes have landed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import config
import db

logger = logging.getLogger(__name__)


# Copied verbatim from the `articles` row. Article-intrinsic columns (url,
# title, text, published, source, verified) are deliberately absent: a reader
# joins back to `articles` for those, so correcting a title or a publish date
# fixes it everywhere rather than leaving every historical snapshot stale.
# Embeddings are absent for a different reason - an embedding describes the
# article's text, not the run, so it would be the same value duplicated into
# every snapshot and it is the widest column in the table.
SNAPSHOT_COLUMNS = (
    "summary",
    "sentiment",
    "sentiment_score",
    "sentiment_low_confidence",
    "sentiment_model",
    "relevance_score",
    "category",
    "article_category",
    "category_confidence",
    "writer_tone",
    "writer_tone_confidence",
    "article_tone",
    "article_tone_confidence",
    "classification_model",
    "insight_json",
    "organizations",
    "entities",
    "topics",
    "key_points",
    "risks",
    "opportunities",
    "brands",
    "car_models",
    "extraction_model",
    "gender",
    "age_range",
    "region",
    "segment",
    "source_language",
    "source_language_confidence",
    "source_domain",
    "analysis_model",
    "analysis_prompt_version",
    "analysis_pipeline_version",
    "analysis_status",
    "analysis_error",
    "analyzed_at",
)

# article_people_opinions is wiped and rewritten on every analysis, so it only
# ever holds the latest run's view. Folding the run's opinions into the snapshot
# as JSON keeps the per-run demographic breakdown without versioning that table
# (and article_tags and article_feedback_items alongside it).
_PEOPLE_OPINIONS_KEYS = (
    ("opinion", "po.opinion"),
    ("sentiment", "po.sentiment"),
    ("category", "po.category"),
    ("gender", "po.gender"),
    # Added by migration 0019, so it is one of the keys here that a database
    # may legitimately not have yet - see _people_opinions_sql().
    ("gender_evidence", "po.gender_evidence"),
    ("age_range", "po.age_range"),
    # Added by migration 0021, same reasoning as gender_evidence above.
    ("age_evidence", "po.age_evidence"),
    ("region", "po.region"),
    ("segment", "po.segment"),
)

# Keys whose column may not exist yet on a database mid-migration-rollout -
# see _people_opinions_sql().
_OPTIONAL_PEOPLE_OPINIONS_KEYS = ("gender_evidence", "age_evidence")


def _people_opinions_sql() -> str:
    """The people-opinions jsonb sub-select, built from the columns this
    database actually has.

    gender_evidence/age_evidence arrived in migrations 0019/0021. Naming one
    unconditionally would make the whole snapshot insert fail on a database
    that hasn't applied that migration yet (MIGRATE_ON_STARTUP=false, or a
    replica mid-rollout) - and because record_analysis_snapshot() swallows
    failures by design, that would silently produce no article_analyses rows
    at all for every article in the run rather than a snapshot missing one
    key. Dropping the key keeps the run comparable; the same reasoning
    guards the write side in store._replace_article_children()."""
    pairs = [
        (key, source) for key, source in _PEOPLE_OPINIONS_KEYS
        if key not in _OPTIONAL_PEOPLE_OPINIONS_KEYS or _table_has_column("article_people_opinions", key)
    ]
    fields = ", ".join(f"'{key}', {source}" for key, source in pairs)
    return f"""
    coalesce((
        select jsonb_agg(jsonb_build_object({fields}) order by po.id)
        from article_people_opinions po
        where po.article_id = a.id
    ), '[]'::jsonb)
"""


def _table_exists(name: str) -> bool:
    try:
        row = db.fetch_one("select to_regclass(%s) as name", (f"public.{name}",))
    except Exception:
        return False
    return bool(row and row.get("name"))


def _table_has_column(table: str, column: str) -> bool:
    """Whether one column exists, for code that has to run against a database
    a migration hasn't reached yet.

    Deliberately not memoized: the answer only ever flips false->true (a column
    is added, never dropped), and caching a false would keep this process
    writing the degraded shape until it restarts even after the migration
    lands. One information_schema lookup per article is nothing beside the
    model call that produced the article's analysis."""
    try:
        row = db.fetch_one(
            """
            select exists (
                select 1 from information_schema.columns
                where table_schema = 'public'
                  and table_name = %s
                  and column_name = %s
            ) as exists
            """,
            (table, column),
        )
    except Exception:
        return False
    return bool(row and row.get("exists"))


def record_analysis_snapshot(run_id: str, article_id: int) -> bool:
    """Freeze this run's conclusions about this article.

    Best-effort by design: a snapshot that fails to write must not turn an
    article the run actually analyzed into a failed one. The run's own counters
    and the article's stored analysis are the primary record; this table is the
    comparison history layered on top.

    Idempotent - re-running the same article inside the same run (a retry)
    overwrites that run's row rather than accumulating duplicates.
    """
    if not run_id or article_id is None:
        return False

    columns = ", ".join(SNAPSHOT_COLUMNS)
    selected = ", ".join(f"a.{column}" for column in SNAPSHOT_COLUMNS)
    updates = ", ".join(f"{column} = excluded.{column}" for column in SNAPSHOT_COLUMNS)

    try:
        db.execute(
            f"""
            insert into article_analyses (run_id, article_id, {columns}, people_opinions)
            select %s, a.id, {selected}, {_people_opinions_sql()}
            from articles a
            where a.id = %s
            on conflict (run_id, article_id) do update
               set {updates},
                   people_opinions = excluded.people_opinions,
                   created_at = now()
            """,
            (str(run_id), int(article_id)),
        )
        return True
    except Exception as exc:
        # Still swallowed - a lost comparison point must not fail an article the
        # run analyzed - but not silently: the caller discards this return value,
        # so without a line here a snapshot that never writes for any article
        # leaves no trace anywhere.
        logger.warning("analysis snapshot not recorded for article %s in run %s: %s", article_id, run_id, exc)
        return False


def fetch_run_article_rows(project_id: int, run_id: str) -> list[dict]:
    """This run's articles, shaped exactly like intelligence._fetch_project_rows'
    unscoped query so both feed the same aggregation code.

    Analysis fields come from the snapshot; identity fields (url, title, text,
    published, verified) come from the live `articles` row, so a run's numbers
    stay frozen while the article's own metadata stays current.

    relevance_score/analysis_status/topics/key_points are additive columns
    (services/reports/report_data.py needs them for ranking and status
    counts) - every existing caller of this function just ignores the extra
    keys, since Postgres row dicts are read by name.
    """
    if not run_id or not _table_exists("article_analyses"):
        return []
    try:
        return db.fetch_all(
            """
            select a.id, a.url, a.source, a.source_url, a.title, a.text, a.verified,
                   a.published, a.created_at, a.pipeline_run_id,
                   an.summary, an.sentiment, an.writer_tone, an.article_tone,
                   an.region, an.gender, an.age_range, an.segment,
                   an.insight_json, an.source_language, an.source_domain,
                   an.relevance_score, an.analysis_status, an.topics, an.key_points,
                   an.run_id
            from article_analyses an
            join articles a          on a.id = an.article_id
            join article_projects ap on ap.article_id = a.id
            where ap.project_id = %s and an.run_id = %s
            order by a.created_at asc
            """,
            (int(project_id), str(run_id)),
        ) or []
    except Exception:
        return []


def sentiment_counts_by_run(project_id: int, run_ids: list) -> dict:
    """{run_id: {sentiment: count}} for this project, straight off the
    snapshots - so a run that re-analyzed articles an earlier run had already
    seen still reports its own totals instead of zero."""
    ids = [str(run_id) for run_id in run_ids or [] if run_id]
    if not ids or not _table_exists("article_analyses"):
        return {}
    try:
        rows = db.fetch_all(
            """
            select an.run_id, an.sentiment, count(*)::int as total
            from article_analyses an
            join article_projects ap on ap.article_id = an.article_id
            where ap.project_id = %s and an.run_id = any(%s)
            group by an.run_id, an.sentiment
            """,
            (int(project_id), ids),
        ) or []
    except Exception:
        return {}

    counts: dict = {}
    for row in rows:
        sentiment = str(row.get("sentiment") or "").lower()
        counts.setdefault(row.get("run_id"), {})[sentiment] = int(row.get("total") or 0)
    return counts


def run_article_count(run_id: str) -> int:
    """How many per-article snapshots this run holds - what a delete would
    discard, shown in the confirmation prompt."""
    if not run_id or not _table_exists("article_analyses"):
        return 0
    try:
        row = db.fetch_one(
            "select count(*)::int as total from article_analyses where run_id = %s",
            (str(run_id),),
        )
    except Exception:
        return 0
    return int((row or {}).get("total") or 0)


# --- Point-in-time reconstruction for the Reports "variation from yesterday" ---
#
# Every bulk analysis run already snapshots its own conclusions here (above).
# The gap is one-off single-article (re)analysis - main.py's .../analyze,
# .../reprocess and batch .../analyze routes call reanalyze_article()/
# reanalyze_articles() with no run_id, so record_analysis_snapshot() was never
# called for them and that change to the article's analysis is invisible to
# any historical query; only the live `articles` row moved. Since
# article_analyses.run_id is a real foreign key into pipeline_runs (not a free
# text field), the fix is not a new table - it's giving those one-off saves a
# real (if synthetic) pipeline_runs row to snapshot against, so every existing
# snapshot reader (fetch_run_article_rows, sentiment_counts_by_run, and the
# point-in-time reconstruction below) keeps working unchanged.
ADHOC_SNAPSHOT_PIPELINE = "report-snapshot"


def _report_tz() -> ZoneInfo:
    try:
        return ZoneInfo(config.REPORT_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def ensure_adhoc_snapshot_run(project_id: int | None, when: datetime | None = None) -> str | None:
    """Find-or-create today's synthetic pipeline_runs row for one-off
    (re)analysis snapshots, one per (project, calendar day in
    config.REPORT_TIMEZONE) so repeated retries the same day share a row
    instead of piling up one adhoc run per click.

    Returns None (best-effort, same contract as record_analysis_snapshot)
    when there is no single project to scope it to - an article linked to
    zero or several projects has no one "project's day" to file the snapshot
    under (see reanalyze._primary_project_id_for_article).

    Deliberately a different `pipeline` value ('report-snapshot') than the
    real analysis pipeline ('analysis') - _fetch_pipeline_runs/list_pipeline_
    runs' run pickers filter on pipeline='analysis', so these synthetic rows
    never show up as a selectable "Analysis run" anywhere in the dashboard;
    they exist purely as an FK anchor for article_analyses.
    """
    if project_id is None or not config.DATABASE_URL:
        return None
    from services.pipeline.pipeline_runs import create_pipeline_run

    moment = when or datetime.now(timezone.utc)
    day = moment.astimezone(_report_tz()).date().isoformat()
    run_id = f"snap-{int(project_id)}-{day}"
    run = create_pipeline_run(
        run_id=run_id,
        pipeline=ADHOC_SNAPSHOT_PIPELINE,
        project_id=int(project_id),
        status="success",
        stage="analyze",
        message="Point-in-time snapshot for historical reporting",
    )
    return run["id"] if run else None


def earliest_snapshot_at(project_id: int) -> datetime | None:
    """The oldest article_analyses row this project has, across every run
    (real or synthetic) - i.e. how far back a "state as of date X" comparison
    can actually reach. None means no historical snapshot exists at all yet,
    which is exactly the "Comparison unavailable" case for any date."""
    if not _table_exists("article_analyses"):
        return None
    try:
        row = db.fetch_one(
            """
            select min(an.created_at) as earliest
            from article_analyses an
            join article_projects ap on ap.article_id = an.article_id
            where ap.project_id = %s
            """,
            (int(project_id),),
        )
    except Exception:
        return None
    value = (row or {}).get("earliest")
    return value


def fetch_state_as_of(project_id: int, cutoff: datetime) -> list[dict]:
    """This project's articles as their analysis stood at or before `cutoff`
    (a tz-aware instant) - one row per article, its latest snapshot no newer
    than the cutoff, across every run (real bulk runs and the adhoc one-off
    rows above). An article with no snapshot at or before the cutoff is
    simply absent, never backfilled from its current (possibly much later)
    state - that would be reconstructing an unknown historical result from
    data that has since been overwritten, which is exactly what this table
    exists to avoid.

    Shaped like intelligence._fetch_project_rows()'s run-scoped output (see
    fetch_run_article_rows above) so callers can reuse the same aggregation
    helpers regardless of which point in time they're looking at.
    """
    if not cutoff or not _table_exists("article_analyses"):
        return []
    try:
        return db.fetch_all(
            """
            select distinct on (an.article_id)
                   an.article_id as id, a.url, a.source, a.source_url, a.title, a.text, a.verified,
                   a.published, a.created_at, a.pipeline_run_id,
                   an.run_id, an.created_at as snapshot_at,
                   an.summary, an.sentiment, an.relevance_score, an.writer_tone, an.article_tone,
                   an.region, an.gender, an.age_range, an.segment,
                   an.insight_json, an.topics, an.key_points, an.source_language, an.source_domain,
                   an.analysis_status
            from article_analyses an
            join articles a          on a.id = an.article_id
            join article_projects ap on ap.article_id = a.id
            where ap.project_id = %s and an.created_at <= %s
            order by an.article_id, an.created_at desc
            """,
            (int(project_id), cutoff),
        ) or []
    except Exception:
        logger.exception("Failed to reconstruct article state as of %s for project %s", cutoff, project_id)
        return []
