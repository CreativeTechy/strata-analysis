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

import db


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
_PEOPLE_OPINIONS_SQL = """
    coalesce((
        select jsonb_agg(jsonb_build_object(
                   'opinion',   po.opinion,
                   'sentiment', po.sentiment,
                   'category',  po.category,
                   'gender',    po.gender,
                   'age_range', po.age_range,
                   'region',    po.region,
                   'segment',   po.segment
               ) order by po.id)
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
            select %s, a.id, {selected}, {_PEOPLE_OPINIONS_SQL}
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
    except Exception:
        return False


def fetch_run_article_rows(project_id: int, run_id: str) -> list[dict]:
    """This run's articles, shaped exactly like intelligence._fetch_project_rows'
    unscoped query so both feed the same aggregation code.

    Analysis fields come from the snapshot; identity fields (url, title, text,
    published, verified) come from the live `articles` row, so a run's numbers
    stay frozen while the article's own metadata stays current.
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
                   an.insight_json, an.source_language,
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
