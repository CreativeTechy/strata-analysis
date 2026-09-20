"""Cross-source idea comparison: for a project's idea_clusters (see
idea_clustering.py) that more than one distinct source has talked about,
build a card showing what each source specifically said - most usefully,
when sources state different values/figures for what is otherwise the same
idea (e.g. one source's stated petrol price vs. another's).

Reuses idea_clusters/idea_cluster_articles rather than re-deriving idea
grouping: those tables already do the embedding-based attach-or-create
clustering of frequent_ideas across a project's articles. This module only
adds the "group by source, did they actually diverge, summarize it" layer on
top, and persists the result (idea_comparisons) the same way
services/intelligence/trend_summary.py caches its LLM paragraph - a plain
call returns whatever is cached, and only an explicit regenerate spends
another LLM call.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import config
import db
from analysis.json_utils import JSONParseError, parse_json_response
from llm_client import chat_completion
from prompt_loader import load_prompt
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)

PROMPT_VERSION = "idea-comparison/1"
_SYSTEM_PROMPT = load_prompt("idea_comparison_system_prompt.txt")

MAX_EXCERPT_LENGTH = 300


def _source_label(row: dict) -> str:
    """Best-effort human-readable source name for an article: the hostname
    of whichever URL it has (source_url for an uploaded-document article,
    else its own url), falling back to the document filename in `source`,
    since this app has no separate publisher/outlet column (see CLAUDE.md -
    there is no scraper or `sources` table here)."""
    for candidate in (row.get("source_url"), row.get("url")):
        text = str(candidate or "").strip()
        if not text:
            continue
        host = urlparse(text).netloc.strip().lower()
        if host:
            return host[4:] if host.startswith("www.") else host
    source = str(row.get("source") or "").strip()
    return source or "Unknown source"


def _cluster_candidates(project_id: int, limit: int, run_id: str | None = None) -> list[dict]:
    # Two steps rather than one join-then-LIMIT query: capping the joined
    # rows directly would truncate a single high-frequency cluster's own
    # articles before ever reaching the next cluster. Picking the top cluster
    # ids first, then fetching every one of *their* articles with no further
    # limit, is what actually bounds this to "at most `limit` clusters".
    #
    # idea_cluster_articles has no run history of its own - each article's row
    # is fully replaced on every (re)analysis (idea_clustering.py's
    # _replace_idea_clusters_for_article), so it only ever reflects whichever
    # run last touched that article, exactly like articles.pipeline_run_id.
    # A run-scoped comparison therefore restricts candidate articles to that
    # column rather than filtering idea_clusters' own (global, cross-run)
    # frequency_estimate.
    if run_id:
        cluster_ids = db.fetch_all(
            """
            select ic.id as id, count(distinct ica.article_id) as run_count
            from idea_clusters ic
            join idea_cluster_articles ica on ica.idea_cluster_id = ic.id
            join articles a on a.id = ica.article_id
            where ic.project_id = %s and a.pipeline_run_id = %s
            group by ic.id
            having count(distinct ica.article_id) >= 2
            order by run_count desc, ic.id desc
            limit %s
            """,
            (int(project_id), str(run_id), int(limit)),
        )
    else:
        cluster_ids = db.fetch_all(
            """
            select id from idea_clusters
            where project_id = %s and frequency_estimate >= 2
            order by frequency_estimate desc, id desc
            limit %s
            """,
            (int(project_id), int(limit)),
        )
    ids = [row["id"] for row in cluster_ids or []]
    if not ids:
        return []
    if run_id:
        return db.fetch_all(
            """
            select ic.id as idea_cluster_id, ic.idea, ic.type, ic.frequency_estimate,
                   a.id as article_id, a.title, a.url, a.source, a.source_url, a.published,
                   a.summary, ica.value
            from idea_clusters ic
            join idea_cluster_articles ica on ica.idea_cluster_id = ic.id
            join articles a on a.id = ica.article_id
            where ic.id = any(%s) and a.pipeline_run_id = %s
            """,
            (ids, str(run_id)),
        )
    return db.fetch_all(
        """
        select ic.id as idea_cluster_id, ic.idea, ic.type, ic.frequency_estimate,
               a.id as article_id, a.title, a.url, a.source, a.source_url, a.published,
               a.summary, ica.value
        from idea_clusters ic
        join idea_cluster_articles ica on ica.idea_cluster_id = ic.id
        join articles a on a.id = ica.article_id
        where ic.id = any(%s)
        """,
        (ids,),
    )


def _group_clusters(rows: list[dict]) -> dict[int, dict]:
    clusters: dict[int, dict] = {}
    for row in rows:
        cluster_id = row["idea_cluster_id"]
        cluster = clusters.setdefault(cluster_id, {
            "idea_cluster_id": cluster_id,
            "idea": row["idea"],
            "type": row["type"],
            "frequency_estimate": row["frequency_estimate"],
            "sources": [],
        })
        cluster["sources"].append({
            "source_label": _source_label(row),
            "value": str(row.get("value") or "").strip(),
            "article_id": row["article_id"],
            "title": row.get("title") or "",
            "url": row.get("url") or "",
            "published": row.get("published"),
            "excerpt": str(row.get("summary") or "")[:MAX_EXCERPT_LENGTH],
        })
    return clusters


def _qualifying_clusters(clusters: dict[int, dict], limit: int) -> list[dict]:
    """Only clusters more than one distinct source contributed to - a single
    source repeating its own idea across several of its own articles is not
    a cross-source comparison. Clusters where sources stated different
    non-empty values are surfaced first (`diverges`), since that is the
    scenario this feature exists for; same-value/no-value clusters ("multiple
    sources agree") fill the remaining slots."""
    diverging, agreeing = [], []
    for cluster in clusters.values():
        distinct_sources = {s["source_label"] for s in cluster["sources"]}
        if len(distinct_sources) < 2:
            continue
        distinct_values = {s["value"].lower() for s in cluster["sources"] if s["value"]}
        cluster["diverges"] = len(distinct_values) >= 2
        (diverging if cluster["diverges"] else agreeing).append(cluster)

    diverging.sort(key=lambda c: -c["frequency_estimate"])
    agreeing.sort(key=lambda c: -c["frequency_estimate"])
    return (diverging + agreeing)[:limit]


def _format_sources(sources: list[dict]) -> str:
    blocks = []
    for index, source in enumerate(sources, start=1):
        stated = f'stated value: "{source["value"]}"' if source["value"] else "no specific figure stated"
        blocks.append(
            f'[{index}] {source["source_label"]} - {stated}\n'
            f'    "{source["title"]}": {source["excerpt"]}'
        )
    return "\n\n".join(blocks)


def _synthesize_summary(cluster: dict) -> str | None:
    user_prompt = f'IDEA: {cluster["idea"]}\n\nSOURCES:\n{_format_sources(cluster["sources"])}'
    raw = chat_completion(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=400,
        json_mode=True,
    )
    try:
        parsed = parse_json_response(raw)
    except JSONParseError as exc:
        logger.warning("Idea comparison summary unparsable for cluster %s: %s", cluster["idea_cluster_id"], exc)
        return None
    if not isinstance(parsed, dict):
        return None
    summary = str(parsed.get("summary") or "").strip()
    return summary or None


def _save_comparison(project_id: int, cluster: dict, summary: str | None, run_id: str | None) -> None:
    db.execute(
        """
        insert into idea_comparisons (
            project_id, idea_cluster_id, run_id, idea, type, diverges, sources, summary,
            article_count, analysis_model, prompt_version, generated_at
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        on conflict (project_id, idea_cluster_id, run_id) do update set
            idea = excluded.idea,
            type = excluded.type,
            diverges = excluded.diverges,
            sources = excluded.sources,
            summary = excluded.summary,
            article_count = excluded.article_count,
            analysis_model = excluded.analysis_model,
            prompt_version = excluded.prompt_version,
            generated_at = excluded.generated_at
        """,
        (
            int(project_id),
            cluster["idea_cluster_id"],
            str(run_id or ""),
            cluster["idea"],
            cluster["type"],
            cluster["diverges"],
            Jsonb(cluster["sources"]),
            summary,
            len(cluster["sources"]),
            config.LLM_CHAT_MODEL or None,
            PROMPT_VERSION,
        ),
    )


def _mark_run_generation_attempt(project_id: int, run_id: str) -> None:
    db.execute(
        """
        insert into idea_comparisons_generation_attempts (project_id, run_id, generated_at)
        values (%s, %s, now())
        on conflict (project_id, run_id) do update set generated_at = now()
        """,
        (int(project_id), str(run_id)),
    )


def has_run_generation_attempt(project_id: int, run_id: str) -> bool:
    """Whether generate_idea_comparisons has already completed (successfully,
    even with zero qualifying clusters) for this run scope.

    idea_comparisons itself can't tell "generated, nothing qualified" apart
    from "never generated" - both read back empty - so without this,
    get_project_idea_comparisons_view would regenerate (and, during a
    provider outage, re-fail) on every single view of a run that genuinely
    has fewer than two cross-source ideas. Only meaningful for a run scope:
    the project-wide view (run_id='') already regenerates only on an
    explicit request, never as a side effect of a plain GET.
    """
    if not config.DATABASE_URL or not run_id:
        return False
    row = db.fetch_one(
        "select 1 from idea_comparisons_generation_attempts where project_id = %s and run_id = %s",
        (int(project_id), str(run_id)),
    )
    return bool(row)


def generate_idea_comparisons(project_id: int, run_id: str | None = None) -> int:
    """(Re)build the comparison cards for a project's qualifying idea
    clusters, either across the whole project (run_id=None) or scoped to one
    analysis run's articles (run_id set). Returns how many were written.

    An LLMError (bad key, provider unreachable, ...) is deliberately NOT
    caught here - it propagates to the caller exactly like
    competitor_analysis.generate_findings does, since it means the provider
    call itself never produced an answer, not "this one cluster had nothing
    to say". Whatever was already written to idea_comparisons in this call
    stays, since each cluster is saved as soon as it is synthesized. Note
    that the run-scoped "already attempted" marker below is only reached once
    every cluster has synthesized successfully - a provider failure partway
    through leaves it unmarked, so the next view retries rather than caching
    a transient outage as "nothing to show".
    """
    if not config.DATABASE_URL:
        return 0

    rows = _cluster_candidates(project_id, config.IDEA_COMPARISON_MAX_CLUSTERS, run_id=run_id)
    clusters = _qualifying_clusters(_group_clusters(rows), config.IDEA_COMPARISON_MAX_CLUSTERS)

    written = 0
    for cluster in clusters:
        summary = _synthesize_summary(cluster)
        _save_comparison(project_id, cluster, summary, run_id)
        written += 1

    if run_id:
        _mark_run_generation_attempt(project_id, run_id)
    return written


def list_idea_comparisons(project_id: int, run_id: str | None = None) -> list[dict]:
    if not config.DATABASE_URL:
        return []
    rows = db.fetch_all(
        """
        select idea_cluster_id, idea, type, diverges, sources, summary,
               article_count, generated_at
        from idea_comparisons
        where project_id = %s and run_id = %s
        order by diverges desc, article_count desc, generated_at desc
        """,
        (int(project_id), str(run_id or "")),
    )
    return [
        {
            "idea_cluster_id": row["idea_cluster_id"],
            "idea": row["idea"],
            "type": row["type"],
            "diverges": bool(row["diverges"]),
            "sources": row["sources"] or [],
            "summary": row["summary"],
            "article_count": int(row["article_count"] or 0),
            "generated_at": row["generated_at"].isoformat() if row["generated_at"] else None,
        }
        for row in rows or []
    ]
