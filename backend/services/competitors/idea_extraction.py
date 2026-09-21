"""Cross-source idea comparisons for competitor studies.

Competitor-mode articles never run the opinion-monitor AI stage pipeline
(analysis.orchestrator.analyze_article) - competitor_analysis.generate_findings
synthesizes its cards straight from raw article text/excerpts instead - so they
never get the frequent_ideas extraction services/articles/idea_comparisons.py
depends on, and idea_clusters/idea_cluster_articles stay empty for a
competitor study's articles.

Running the full stage pipeline just to get one field would be wasteful - a
competitor study never reads sentiment/classification/entities/embeddings -
so this runs only the structured-extraction stage (the same LLM call an
opinion-monitor article's analysis gets, minus everything orchestrator.py
bolts on around it) and links the result into idea_clusters directly via
idea_clustering._replace_idea_clusters_for_article, the same function
save_articles() calls for opinion-monitor articles.
"""

from __future__ import annotations

import logging

import db
from analysis.structured_extraction import extract_structured_data
from services.articles.analysis_defaults import FATAL_ANALYSIS_ERRORS
from services.articles.idea_clustering import _replace_idea_clusters_for_article

logger = logging.getLogger(__name__)


def _extract_one(article: dict, project_id: int) -> bool:
    extraction = extract_structured_data(article.get("title") or "", article.get("text") or "")
    if extraction.failed:
        db.execute(
            "update articles set analysis_status = 'failed', analysis_error = %s where id = %s",
            (extraction.reason, article["id"]),
        )
        return False

    frequent_ideas = extraction.data.get("frequent_ideas") or []
    summary = extraction.data.get("summary") or ""
    db.execute(
        """
        update articles set
            summary = coalesce(nullif(%s, ''), summary),
            analysis_status = 'success',
            analysis_error = null
        where id = %s
        """,
        (summary, article["id"]),
    )
    _replace_idea_clusters_for_article(article["id"], project_id, frequent_ideas)
    return True


def extract_frequent_ideas_for_documents(project_id: int, document_ids: list[int] | None = None, log=None) -> int:
    """Runs the lightweight frequent_ideas extraction over every approved
    article that hasn't had it run yet - scoped to `document_ids` when given
    (an analysis run's resolved document set), or every approved article in
    the project when it's None (document_analysis.analyze_documents has no
    document scope of its own - it reads everything approved, the same way
    generate_findings(project_id, period_days=None) does for it). An empty
    list is a real "nothing in scope", not "no filter" - it's what an
    analysis run with an empty resolved scope would pass, and there's nothing
    to do with that.

    `analysis_status` starts 'pending' and is otherwise never touched for a
    competitor study's articles (see schema.sql's comment: "'failed'/
    'pending'/'processing' mean the pipeline has actually seen the row"), so
    it doubles as this step's idempotency marker - each article only ever
    pays for this extraction once, not on every analysis run.

    Best-effort per article: one bad response doesn't stop the rest, the same
    per-item isolation generate_findings uses for competitors. A
    FATAL_ANALYSIS_ERRORS failure (bad credentials, provider unreachable,
    ...) does propagate, since every remaining call would fail identically -
    the caller already turns an uncaught exception into a failed/errored run.

    Returns how many articles were successfully extracted.
    """
    log = log or (lambda _message: None)
    if document_ids is not None and not document_ids:
        return 0

    scope_clause = "and cda.document_id = any(%s)" if document_ids else ""
    params = [int(project_id)]
    if document_ids:
        params.append([int(d) for d in document_ids])

    articles = db.fetch_all(
        f"""
        select a.id, a.title, a.text
        from articles a
        join competitor_document_articles cda on cda.article_id = a.id
        where cda.project_id = %s and cda.status = 'approved'
          {scope_clause}
          and coalesce(a.analysis_status, 'pending') != 'success'
        """,
        tuple(params),
    )
    if not articles:
        return 0

    log(f"Extracting recurring ideas from {len(articles)} article{'' if len(articles) == 1 else 's'}...")
    extracted = 0
    for article in articles:
        try:
            if _extract_one(article, project_id):
                extracted += 1
        except FATAL_ANALYSIS_ERRORS:
            raise
        except Exception as exc:
            logger.warning("Frequent-ideas extraction failed for article %s: %s", article["id"], exc)
    return extracted
