"""Article browsing API: composes articles_query (plain fetch),
articles_search (ranking), and articles_analytics (rollups) into the one
surface main.py's article routes call.

list_articles()/export_articles() are the only real logic left here - each
decides per-call whether a search term routes through articles_search or a
plain articles_query fetch, then attaches project similarity scores the same
way either way. Everything else below is a re-export so callers that already
`from services.articles.articles_store import X` don't need to know the
implementation moved.
"""

from __future__ import annotations

from services.articles.articles_analytics import (  # noqa: F401 - re-exported
    compute_overall_tone,
    get_article_stats,
)
from services.articles.articles_query import (
    BULK_PAGE_SIZE,  # noqa: F401 - re-exported
    DEFAULT_LIMIT,
    DEFAULT_SORT,
    MAX_LIMIT,  # noqa: F401 - re-exported
    ARTICLES_SELECT,
    _export_select,
    _fetch_articles,
    _normalize_limit,
    _normalize_offset,
    _normalize_sort,
    _normalize_text,
    _attach_project_similarity_scores,
    get_analysis_status_counts,  # noqa: F401 - re-exported
    get_article_analysis,  # noqa: F401 - re-exported
    list_analysis_errors,  # noqa: F401 - re-exported
    list_articles_for_idea_cluster,  # noqa: F401 - re-exported
    list_idea_clusters_for_project,  # noqa: F401 - re-exported
)
from services.articles.articles_search import search_results


def list_articles(search=None, sentiment=None, category=None, project_id=None, limit=DEFAULT_LIMIT, offset=0, sort=DEFAULT_SORT, source_url=None, added_from=None, added_to=None):
    limit = _normalize_limit(limit)
    offset = _normalize_offset(offset)
    field, direction = _normalize_sort(sort)

    search_text = _normalize_text(search)
    if search_text:
        rows, total = search_results(
            search=search_text,
            sentiment=sentiment,
            category=category,
            project_id=project_id,
            source_url=source_url,
            added_from=added_from,
            added_to=added_to,
        )
        rows = rows[offset:offset + limit]
        rows = _attach_project_similarity_scores(rows, project_id)
        return {
            "articles": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
            "sort": "semantic.desc",
        }

    rows, total = _fetch_articles(
        limit=limit,
        offset=offset,
        search=search,
        sentiment=sentiment,
        category=category,
        project_id=project_id,
        order=f"{field}.{direction}",
        select=ARTICLES_SELECT,
        source_url=source_url,
        added_from=added_from,
        added_to=added_to,
    )
    rows = _attach_project_similarity_scores(rows, project_id)
    return {
        "articles": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": f"{field}.{direction}",
    }


def export_articles(search=None, sentiment=None, category=None, project_id=None, sort=DEFAULT_SORT, source_url=None, added_from=None, added_to=None):
    """Yield full article rows for the JSONL export, one page at a time.

    A generator rather than a list: the export carries `text` and
    `embedding_json` for every row (see articles_query._export_select() for
    why it reads a wider column list than list_articles() does), so
    materializing a whole project's worth before the response starts is what
    would put a ceiling on how large a project can be exported. Streaming
    holds one page at a time and lets the client start receiving immediately.

    Callers that genuinely need them all at once can still wrap it in list().
    The similarity scores are looked up once here rather than per page.
    """
    from services.articles.articles_query import _apply_similarity_scores, _project_similarity_scores

    select = _export_select()
    scores = _project_similarity_scores(project_id)
    search_text = _normalize_text(search)
    if search_text:
        # The semantic path ranks a bounded scan (SEARCH_SCAN_LIMIT) as a whole,
        # so this page is already materialized - stream it out as one chunk.
        rows, _ = search_results(
            search=search_text,
            sentiment=sentiment,
            category=category,
            project_id=project_id,
            source_url=source_url,
            added_from=added_from,
            added_to=added_to,
            select=select,
        )
        yield from _apply_similarity_scores(rows, scores)
        return

    page_size = BULK_PAGE_SIZE
    offset = 0
    field, direction = _normalize_sort(sort)

    while True:
        batch, _ = _fetch_articles(
            limit=page_size,
            offset=offset,
            search=search,
            sentiment=sentiment,
            category=category,
            project_id=project_id,
            order=f"{field}.{direction}",
            select=select,
            source_url=source_url,
            added_from=added_from,
            added_to=added_to,
            max_limit=page_size,
        )
        if not batch:
            return
        yield from _apply_similarity_scores(batch, scores)
        if len(batch) < page_size:
            return
        offset += len(batch)
