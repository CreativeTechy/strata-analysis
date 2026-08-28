"""Keyword + semantic ranking over the article corpus.

`search_results()` is the entry point articles_store.py's list_articles()/
export_articles() call when a search term is present; `_fetch_all_articles`
is this module's own bounded bulk-scan reader (built on
articles_query._fetch_articles) rather than a generic pagination helper -
SEARCH_SCAN_LIMIT is a hard ceiling on how much of the corpus one search ever
ranks in memory, and nothing outside this module needs an unbounded scan.
"""

from __future__ import annotations

import re

import config
from embeddings import cosine_similarity, get_embedding
from services.articles.articles_query import (
    ARTICLES_SELECT,
    DEFAULT_SORT,
    _fetch_articles,
    _normalize_text,
)

SEARCH_SCAN_LIMIT = 1000


def _fetch_all_articles(search=None, sentiment=None, category=None, project_id=None, *, select=ARTICLES_SELECT, order=DEFAULT_SORT, limit=SEARCH_SCAN_LIMIT, date_from=None, date_to=None, source_url=None, added_from=None, added_to=None):
    if not config.DATABASE_URL:
        return []

    rows = []
    page_size = 500
    offset = 0
    limit = max(1, min(int(limit or SEARCH_SCAN_LIMIT), SEARCH_SCAN_LIMIT))

    while len(rows) < limit:
        want = min(page_size, limit - len(rows))
        batch, _ = _fetch_articles(
            limit=want,
            offset=offset,
            search=search,
            sentiment=sentiment,
            category=category,
            project_id=project_id,
            order=order,
            select=select,
            date_from=date_from,
            date_to=date_to,
            source_url=source_url,
            added_from=added_from,
            added_to=added_to,
            max_limit=page_size,
        )
        if not batch:
            break
        rows.extend(batch)
        # A page shorter than the one asked for is the end of the result set -
        # compare against `want`, not page_size, since the final page is
        # deliberately trimmed to the remaining budget.
        if len(batch) < want:
            break
        offset += len(batch)

    return rows[:limit]


def _search_query_embedding(search: str):
    text = _normalize_text(search)
    if not text:
        return []

    embedding = get_embedding(text, role="query")
    if not embedding:
        return []
    vector = embedding.get("embedding_json") or []
    return vector if isinstance(vector, list) else []


def _article_search_blob(row: dict) -> str:
    insight = row.get("insight_json") if isinstance(row.get("insight_json"), dict) else {}
    parts = [
        row.get("title"),
        row.get("summary"),
        row.get("text"),
        row.get("source"),
        row.get("source_url"),
        row.get("author"),
        insight.get("topic"),
        insight.get("summary"),
        row.get("article_category"),
        row.get("category"),
    ]
    return " ".join(_normalize_text(value).lower() for value in parts if _normalize_text(value))


def _score_search_row(row: dict, search: str, query_embedding: list[float] | None = None):
    search_text = _normalize_text(search).lower()
    if not search_text:
        return 0.0, False

    blob = _article_search_blob(row)
    if not blob:
        return 0.0, False

    tokens = [token for token in re.split(r"\W+", search_text) if len(token) > 1]
    keyword_hits = sum(1 for token in tokens if token in blob)
    exact_phrase_hit = search_text in blob
    keyword_score = 0.0
    if tokens:
        keyword_score = min(1.0, keyword_hits / len(tokens))
    elif exact_phrase_hit:
        keyword_score = 1.0

    semantic_score = 0.0
    if query_embedding:
        candidate_embedding = row.get("embedding_json") or []
        if isinstance(candidate_embedding, list) and candidate_embedding:
            semantic_score = max(0.0, cosine_similarity(query_embedding, candidate_embedding))

    score = max(keyword_score, semantic_score)
    if exact_phrase_hit:
        score = min(1.0, score + 0.1)
    elif keyword_score and semantic_score:
        score = min(1.0, (keyword_score * 0.45) + (semantic_score * 0.55))

    # Every token has to hit, not just one - a query like "Stellantis battery"
    # must not match every article merely because "Stellantis" (the brand
    # name in this project's every title) is present on its own.
    keyword_match = bool(tokens) and keyword_hits == len(tokens)
    matched = exact_phrase_hit or keyword_match or semantic_score >= config.SEARCH_SEMANTIC_MATCH_THRESHOLD
    return score, matched


def _rank_search_rows(rows, search: str):
    search_text = _normalize_text(search)
    if not search_text or not rows:
        return rows, []

    query_embedding = _search_query_embedding(search_text)
    ranked = []
    matched_rows = []
    for index, row in enumerate(rows):
        score, matched = _score_search_row(row, search_text, query_embedding)
        ranked.append((score, matched, index, row))
        if matched:
            matched_rows.append(row)

    ranked_rows = [
        row
        for score, matched, index, row in sorted(
            ranked,
            key=lambda item: (
                -item[0],
                item[2],
            ),
        )
        if matched
    ]
    if not ranked_rows:
        ranked_rows = [row for _, _, _, row in sorted(ranked, key=lambda item: (-item[0], item[2]))[:50]]
        matched_rows = ranked_rows
    return ranked_rows, matched_rows


def search_results(search=None, sentiment=None, category=None, project_id=None, date_from=None, date_to=None, source_url=None, added_from=None, added_to=None, select=ARTICLES_SELECT):
    rows = _fetch_all_articles(
        sentiment=sentiment,
        category=category,
        project_id=project_id,
        select=select,
        order=DEFAULT_SORT,
        limit=SEARCH_SCAN_LIMIT,
        date_from=date_from,
        date_to=date_to,
        source_url=source_url,
        added_from=added_from,
        added_to=added_to,
    )
    ranked_rows, matched_rows = _rank_search_rows(rows, search)
    if _normalize_text(search):
        visible_rows = ranked_rows
        return visible_rows, len(visible_rows)
    return ranked_rows, len(ranked_rows)
