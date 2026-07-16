"""Read helpers for the articles table."""

from __future__ import annotations

from collections import Counter
import re

import config
import db
from embeddings import cosine_similarity, get_embedding
from projects_store import list_article_ids_for_project, list_article_similarity_scores_for_project

ARTICLES_SELECT = (
    "id,url,source,source_url,title,author,published,text,fetched_at,summary,"
    "sentiment,relevance_score,category,article_category,writer_tone,article_tone,insight_json,analysis_model,"
    "analysis_prompt_version,analyzed_at,organizations,entities,topics,key_points,"
    "risks,opportunities,brands,car_models,embedding_json,embedding_model,embedding_source,embedded_at,created_at"
)

VALID_TONES = {
    "neutral",
    "positive",
    "enthusiastic",
    "optimistic",
    "critical",
    "skeptical",
    "negative",
    "concerned",
    "angry",
    "sarcastic",
    "humorous",
    "formal",
    "informal",
}

SORTABLE_COLUMNS = {
    "published",
    "relevance_score",
    "created_at",
    "title",
    "source",
    "category",
    "sentiment",
}

MAX_LIMIT = 100
DEFAULT_LIMIT = 24
DEFAULT_SORT = "published.desc"
SEARCH_SCAN_LIMIT = 1000
SEARCH_MATCH_THRESHOLD = 0.28


def _auth_headers():
    return {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Accept": "application/json",
    }


def _base_endpoint():
    return f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/articles"


def _parse_total(content_range: str | None, fallback: int = 0) -> int:
    if not content_range or "/" not in content_range:
        return fallback
    try:
        total = content_range.rsplit("/", 1)[-1]
        return int(total) if total != "*" else fallback
    except Exception:
        return fallback


def _normalize_text(value: str | None) -> str:
    return (value or "").strip()


def _normalize_sentiment(value: str | None) -> str:
    return _normalize_text(value).lower()


def _normalize_category(value: str | None) -> str:
    return _normalize_text(value).lower()


def _normalize_article_category(value: str | None) -> str:
    return _normalize_text(value).lower() or "general_article"


def _normalize_tone(value: str | None) -> str:
    tone = _normalize_text(value).lower()
    return tone if tone in VALID_TONES else "neutral"


def compute_overall_tone(article_tone, writer_tone):
    """Deterministic overall_tone for a single article. Never guessed by the AI."""
    article_tone = _normalize_tone(article_tone)
    writer_tone = _normalize_tone(writer_tone)
    if article_tone == writer_tone:
        return article_tone
    if article_tone == "neutral" and writer_tone != "neutral":
        return writer_tone
    if writer_tone == "neutral" and article_tone != "neutral":
        return article_tone
    return "mixed"


def _group_overall_tone(article_tone_counts, writer_tone_counts):
    """Deterministic overall_tone for a collection of articles (project rollup).

    Prefers the most frequent non-neutral article_tone; falls back to
    writer_tone only as a tie-breaker/fallback; "mixed" on conflict.
    """
    non_neutral_article = [(tone, count) for tone, count in article_tone_counts.items() if tone != "neutral" and count]
    if non_neutral_article:
        top_count = max(count for _, count in non_neutral_article)
        top_tones = {tone for tone, count in non_neutral_article if count == top_count}
        if len(top_tones) == 1:
            return next(iter(top_tones))
        tie_break = [(tone, count) for tone, count in writer_tone_counts.items() if tone in top_tones and count]
        if tie_break:
            tie_break.sort(key=lambda item: -item[1])
            return tie_break[0][0]
        return "mixed"

    non_neutral_writer = [(tone, count) for tone, count in writer_tone_counts.items() if tone != "neutral" and count]
    if non_neutral_writer:
        top_count = max(count for _, count in non_neutral_writer)
        top_tones = {tone for tone, count in non_neutral_writer if count == top_count}
        if len(top_tones) == 1:
            return next(iter(top_tones))
        return "mixed"

    return "neutral"


def _normalize_limit(value, default=DEFAULT_LIMIT):
    try:
        limit = int(value)
    except Exception:
        limit = default
    return max(1, min(limit, MAX_LIMIT))


def _normalize_offset(value):
    try:
        offset = int(value)
    except Exception:
        offset = 0
    return max(0, offset)


def _normalize_sort(value: str | None):
    raw = _normalize_text(value) or DEFAULT_SORT
    direction = "desc"
    field = raw

    if raw.startswith("-"):
        field = raw[1:]
        direction = "desc"
    elif "." in raw:
        parts = raw.split(".", 1)
        field = parts[0]
        direction = parts[1] if parts[1] in {"asc", "desc"} else "desc"
    elif raw.endswith("_asc"):
        field = raw[:-4]
        direction = "asc"
    elif raw.endswith("_desc"):
        field = raw[:-5]
        direction = "desc"

    if field not in SORTABLE_COLUMNS:
        field = "published"

    return field, direction


def _where_parts(search=None, sentiment=None, category=None, project_id=None):
    clauses = []
    params = []

    term = _normalize_text(search)
    if term:
        escaped = term.replace(",", " ").replace("%", "").replace("*", "")
        pattern = f"%{escaped}%"
        clauses.append(
            "("
            "title ilike %s or summary ilike %s or text ilike %s or "
            "source ilike %s or source_url ilike %s or author ilike %s"
            ")"
        )
        params.extend([pattern] * 6)

    sentiment_value = _normalize_sentiment(sentiment)
    if sentiment_value and sentiment_value != "all":
        clauses.append("sentiment = %s")
        params.append(sentiment_value)

    category_value = _normalize_category(category)
    if category_value and category_value != "all":
        clauses.append("category = %s")
        params.append(category_value)

    if project_id is not None:
        article_ids = list_article_ids_for_project(project_id)
        if not article_ids:
            clauses.append("id = -1")
        else:
            clauses.append("id = any(%s)")
            params.append(article_ids)

    if clauses:
        return " where " + " and ".join(clauses), params
    return "", params


def _fetch_articles(limit=None, offset=None, search=None, sentiment=None, category=None, project_id=None, order="published.desc", select=ARTICLES_SELECT):
    if not config.DATABASE_URL:
        return [], 0

    field, direction = _normalize_sort(order)
    limit = _normalize_limit(limit)
    offset = _normalize_offset(offset)
    where_sql, params = _where_parts(search=search, sentiment=sentiment, category=category, project_id=project_id)

    try:
        rows = db.fetch_all(
            f"""
            select {select}
            from articles
            {where_sql}
            order by {field} {direction}
            limit %s offset %s
            """,
            (*params, limit, offset),
        )
        count_row = db.fetch_one(
            f"""
            select count(*)::int as total
            from articles
            {where_sql}
            """,
            tuple(params),
        )
        total = int((count_row or {}).get("total") or len(rows))
        return rows, total
    except Exception:
        return [], 0


def _fetch_all_articles(search=None, sentiment=None, category=None, project_id=None, *, select=ARTICLES_SELECT, order=DEFAULT_SORT, limit=SEARCH_SCAN_LIMIT):
    if not config.DATABASE_URL:
        return []

    rows = []
    page_size = 200
    offset = 0
    limit = max(1, min(int(limit or SEARCH_SCAN_LIMIT), SEARCH_SCAN_LIMIT))

    while len(rows) < limit:
        batch, _ = _fetch_articles(
            limit=min(page_size, limit - len(rows)),
            offset=offset,
            search=search,
            sentiment=sentiment,
            category=category,
            project_id=project_id,
            order=order,
            select=select,
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    return rows[:limit]


def _attach_project_similarity_scores(rows, project_id):
    if project_id is None or not rows:
        return rows

    scores = list_article_similarity_scores_for_project(project_id)
    if not scores:
        return rows

    for row in rows:
        try:
            article_id = int(row.get("id"))
        except Exception:
            continue
        if article_id in scores:
            row["project_similarity_score"] = scores[article_id]
    return rows


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

    matched = exact_phrase_hit or keyword_hits > 0 or semantic_score >= SEARCH_MATCH_THRESHOLD
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
        if matched or score > 0
    ]
    if not ranked_rows:
        ranked_rows = [row for _, _, _, row in sorted(ranked, key=lambda item: (-item[0], item[2]))[:50]]
        matched_rows = ranked_rows
    return ranked_rows, matched_rows


def _search_results(search=None, sentiment=None, category=None, project_id=None):
    rows = _fetch_all_articles(
        sentiment=sentiment,
        category=category,
        project_id=project_id,
        select=ARTICLES_SELECT,
        order=DEFAULT_SORT,
        limit=SEARCH_SCAN_LIMIT,
    )
    ranked_rows, matched_rows = _rank_search_rows(rows, search)
    if _normalize_text(search):
        visible_rows = ranked_rows
        return visible_rows, len(visible_rows)
    return ranked_rows, len(ranked_rows)


def _fetch_rows_for_stats(search=None, category=None, project_id=None, limit=1000):
    if not config.DATABASE_URL:
        return []

    rows = []
    page_size = max(1, min(int(limit or 1000), 200))
    offset = 0

    while True:
        batch, _ = _fetch_articles(
            limit=page_size,
            offset=offset,
            search=search,
            category=category,
            project_id=project_id,
            order="created_at.desc",
            select="url,title,sentiment,category,article_category,writer_tone,article_tone,insight_json,summary",
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    return rows


def _list_top_items(values, limit=6):
    cleaned = []
    counts = Counter()
    display = {}
    sources = {}
    for value in values:
        if isinstance(value, dict):
            text = _normalize_text(value.get("text") or value.get("idea") or value.get("opinion") or value.get("feedback"))
            source_url = _normalize_text(value.get("url"))
            source_title = _normalize_text(value.get("title"))
        else:
            text = _normalize_text(value)
            source_url = ""
            source_title = ""
        if not text:
            continue
        key = text.lower()
        counts[key] += 1
        if key not in display:
            display[key] = text
        if source_url or source_title:
            sources.setdefault(key, [])
            source_entry = {"url": source_url, "title": source_title or source_url}
            if source_entry not in sources[key]:
                sources[key].append(source_entry)
    for key, count in counts.most_common(limit):
        item = {"text": display[key], "count": count}
        if key in sources:
            item["sources"] = sources[key]
        cleaned.append(item)
    return cleaned


def _normalize_feedback_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        items = [part.strip() for part in value.replace("\n", ",").split(",")]
    else:
        items = [value]

    cleaned = []
    for item in items:
        if isinstance(item, dict):
            text = _normalize_text(item.get("idea") or item.get("opinion") or item.get("text") or item.get("feedback"))
        else:
            text = _normalize_text(item)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _normalize_people_opinions(value):
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        opinion = _normalize_text(item.get("opinion"))
        if not opinion:
            continue
        sentiment = _normalize_text(item.get("sentiment")).lower() or "neutral"
        category = _normalize_text(item.get("category"))
        key = (opinion.lower(), sentiment, category.lower())
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "opinion": opinion,
            "sentiment": sentiment if sentiment in {"positive", "negative", "mixed", "neutral"} else "neutral",
            "category": category,
        })
    return result


def _normalize_frequent_ideas(value):
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        idea = _normalize_text(item.get("idea"))
        if not idea:
            continue
        type_value = _normalize_text(item.get("type")).lower()
        if type_value not in {"complaint", "praise", "suggestion", "issue"}:
            type_value = "issue"
        category = _normalize_text(item.get("category"))
        key = (idea.lower(), type_value, category.lower())
        if key in seen:
            continue
        seen.add(key)
        try:
            freq = int(float(item.get("frequency_estimate", 1)))
        except Exception:
            freq = 1
        result.append({
            "idea": idea,
            "type": type_value,
            "category": category,
            "frequency_estimate": max(1, freq),
        })
    return result


def _article_category_counts(rows):
    counts = Counter()
    for row in rows:
        category = _normalize_article_category(row.get("article_category") or row.get("category"))
        counts[category] += 1
    return [{"category": category, "count": count} for category, count in counts.most_common()]


def _overall_sentiment(rows):
    counts = Counter()
    for row in rows:
        sentiment = _normalize_sentiment(row.get("sentiment"))
        counts[sentiment] += 1
    positive = counts["positive"]
    negative = counts["negative"]
    mixed = counts["mixed"]
    neutral = counts["neutral"]
    if negative > positive and negative >= neutral:
        return "negative"
    if positive > negative and positive >= neutral:
        return "positive"
    if mixed:
        return "mixed"
    return "neutral"


def _tone_counts(rows, field):
    counts = Counter()
    for row in rows:
        insight = row.get("insight_json") if isinstance(row.get("insight_json"), dict) else {}
        counts[_normalize_tone(row.get(field) or insight.get(field))] += 1
    return counts


def _overall_mood_from_counts(article_tone_counts):
    return article_tone_counts.most_common(1)[0][0] if article_tone_counts else "neutral"


def _topic_summary(rows):
    positive_feedback = []
    negative_feedback = []
    nice_to_have_features = []
    complaints = []
    great_features = []
    comfort_issues = []
    performance_feedback = []
    price_value_feedback = []
    maintenance_reliability_feedback = []
    technology_feedback = []
    safety_feedback = []
    people_opinions = []
    frequent_ideas = []
    topics = []

    for row in rows:
        row_source = {
            "url": _normalize_text(row.get("url")),
            "title": _normalize_text(row.get("title")),
        }
        insight = row.get("insight_json") if isinstance(row.get("insight_json"), dict) else {}
        for text in _normalize_feedback_list(insight.get("positive_feedback")):
            positive_feedback.append({**row_source, "text": text})
        for text in _normalize_feedback_list(insight.get("negative_feedback")):
            negative_feedback.append({**row_source, "text": text})
        for text in _normalize_feedback_list(insight.get("nice_to_have_features")):
            nice_to_have_features.append({**row_source, "text": text})
        for text in _normalize_feedback_list(insight.get("complaints")):
            complaints.append({**row_source, "text": text})
        for text in _normalize_feedback_list(insight.get("great_features")):
            great_features.append({**row_source, "text": text})
        for text in _normalize_feedback_list(insight.get("comfort_issues")):
            comfort_issues.append({**row_source, "text": text})
        for text in _normalize_feedback_list(insight.get("performance_feedback")):
            performance_feedback.append({**row_source, "text": text})
        for text in _normalize_feedback_list(insight.get("price_value_feedback")):
            price_value_feedback.append({**row_source, "text": text})
        for text in _normalize_feedback_list(insight.get("maintenance_reliability_feedback")):
            maintenance_reliability_feedback.append({**row_source, "text": text})
        for text in _normalize_feedback_list(insight.get("technology_feedback")):
            technology_feedback.append({**row_source, "text": text})
        for text in _normalize_feedback_list(insight.get("safety_feedback")):
            safety_feedback.append({**row_source, "text": text})
        people_opinions.extend(_normalize_people_opinions(insight.get("people_opinions")))
        for item in _normalize_frequent_ideas(insight.get("frequent_ideas")):
            frequent_ideas.append({**item, **row_source})
        topic = _normalize_text(insight.get("topic") or row.get("title"))
        if topic:
            topics.append(topic)

    idea_counts = Counter()
    idea_display = {}
    idea_type = {}
    idea_category = {}
    idea_sources = {}
    for item in frequent_ideas:
        idea = _normalize_text(item.get("idea"))
        if not idea:
            continue
        key = idea.lower()
        idea_counts[key] += 1
        idea_display.setdefault(key, idea)
        idea_type.setdefault(key, item.get("type") or "issue")
        idea_category.setdefault(key, item.get("category") or "")
        if item.get("url") or item.get("title"):
            idea_sources.setdefault(key, [])
            source_entry = {
                "url": _normalize_text(item.get("url")),
                "title": _normalize_text(item.get("title")) or _normalize_text(item.get("url")),
            }
            if source_entry not in idea_sources[key]:
                idea_sources[key].append(source_entry)

    frequent_ideas_rollup = [
        {
            "idea": idea_display[key],
            "type": idea_type.get(key, "issue"),
            "category": idea_category.get(key, ""),
            "frequency_estimate": count,
            **({"sources": idea_sources.get(key, [])} if idea_sources.get(key) else {}),
        }
        for key, count in idea_counts.most_common()
    ]

    def as_top_items(values):
        return _list_top_items(values)

    positive_items = as_top_items(positive_feedback + great_features)
    negative_items = as_top_items(negative_feedback + complaints + comfort_issues)
    request_items = as_top_items(nice_to_have_features)

    summary_bits = []
    if positive_items:
        summary_bits.append(f"People like {positive_items[0]['text'].rstrip('.')}.")
    if negative_items:
        summary_bits.append(f"Common concerns include {negative_items[0]['text'].rstrip('.')}.")
    if request_items:
        summary_bits.append(f"Requested improvements center on {request_items[0]['text'].rstrip('.')}.")
    if not summary_bits and frequent_ideas_rollup:
        summary_bits.append(f"The most repeated idea is {frequent_ideas_rollup[0]['idea'].rstrip('.')}.")
    summary = " ".join(summary_bits).strip()

    writer_tone_counts = _tone_counts(rows, "writer_tone")
    article_tone_counts = _tone_counts(rows, "article_tone")

    return {
        "summary": summary,
        "topic": topics[0] if topics else "",
        "article_category_breakdown": _article_category_counts(rows),
        "overall_sentiment": _overall_sentiment(rows),
        "overall_mood": _overall_mood_from_counts(article_tone_counts),
        "overall_tone": _group_overall_tone(article_tone_counts, writer_tone_counts),
        "writer_tone_breakdown": [{"tone": tone, "count": count} for tone, count in writer_tone_counts.most_common()],
        "article_tone_breakdown": [{"tone": tone, "count": count} for tone, count in article_tone_counts.most_common()],
        "positive_feedback": positive_items,
        "negative_feedback": negative_items,
        "nice_to_have_features": request_items,
        "complaints": as_top_items(complaints),
        "great_features": as_top_items(great_features),
        "comfort_issues": as_top_items(comfort_issues),
        "performance_feedback": as_top_items(performance_feedback),
        "price_value_feedback": as_top_items(price_value_feedback),
        "maintenance_reliability_feedback": as_top_items(maintenance_reliability_feedback),
        "technology_feedback": as_top_items(technology_feedback),
        "safety_feedback": as_top_items(safety_feedback),
        "people_opinions": people_opinions[:10],
        "frequent_ideas": frequent_ideas_rollup[:12],
    }


def list_articles(search=None, sentiment=None, category=None, project_id=None, limit=DEFAULT_LIMIT, offset=0, sort=DEFAULT_SORT):
    limit = _normalize_limit(limit)
    offset = _normalize_offset(offset)
    field, direction = _normalize_sort(sort)

    search_text = _normalize_text(search)
    if search_text:
        rows, total = _search_results(
            search=search_text,
            sentiment=sentiment,
            category=category,
            project_id=project_id,
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
    )
    rows = _attach_project_similarity_scores(rows, project_id)
    return {
        "articles": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": f"{field}.{direction}",
    }


def export_articles(search=None, sentiment=None, category=None, project_id=None, sort=DEFAULT_SORT):
    search_text = _normalize_text(search)
    if search_text:
        rows, _ = _search_results(
            search=search_text,
            sentiment=sentiment,
            category=category,
            project_id=project_id,
        )
        return _attach_project_similarity_scores(rows, project_id)

    rows = []
    page_size = 200
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
            select=ARTICLES_SELECT,
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    return _attach_project_similarity_scores(rows, project_id)


def _count_articles(search=None, sentiment=None, category=None, project_id=None):
    search_text = _normalize_text(search)
    if search_text:
        _, total = _search_results(
            search=search_text,
            sentiment=sentiment,
            category=category,
            project_id=project_id,
        )
        return total

    _, total = _fetch_articles(
        limit=1,
        offset=0,
        search=search,
        sentiment=sentiment,
        category=category,
        project_id=project_id,
        order=DEFAULT_SORT,
        select="id",
    )
    return total


def get_article_stats(search=None, category=None, project_id=None):
    total = _count_articles(search=search, category=category, project_id=project_id)
    positive = _count_articles(search=search, sentiment="positive", category=category, project_id=project_id)
    negative = _count_articles(search=search, sentiment="negative", category=category, project_id=project_id)
    neutral = _count_articles(search=search, sentiment="neutral", category=category, project_id=project_id)
    mixed = _count_articles(search=search, sentiment="mixed", category=category, project_id=project_id)
    search_text = _normalize_text(search)
    if search_text:
        rows, _ = _search_results(search=search_text, category=category, project_id=project_id)
    else:
        rows = _fetch_rows_for_stats(search=search, category=category, project_id=project_id)

    return {
        "total": total,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "mixed": mixed,
        "article_category_breakdown": _article_category_counts(rows),
        "insights": _topic_summary(rows),
    }


