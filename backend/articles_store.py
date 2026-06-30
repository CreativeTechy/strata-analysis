"""Read helpers for the articles table.

These helpers keep the Supabase REST query shape in one place so the API can
offer stable pagination and filtering without the dashboard talking to Supabase
directly.
"""

from __future__ import annotations

import requests
from collections import Counter

import config
from events_store import list_article_ids_for_event

ARTICLES_SELECT = (
    "id,url,source,feed,title,author,published,text,fetched_at,summary,"
    "sentiment,relevance_score,category,article_category,insight_json,analysis_model,"
    "analysis_prompt_version,analyzed_at,organizations,entities,topics,key_points,"
    "risks,opportunities,brands,car_models,created_at"
)

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


def _apply_search(params: dict, search: str | None):
    term = _normalize_text(search)
    if not term:
        return

    # Keep the search server-side with a Supabase/PostgREST OR clause.
    escaped = term.replace(",", " ").replace("%", "").replace("*", "")
    pattern = f"%{escaped}%"
    params["or"] = ",".join(
        [
            f"title.ilike.{pattern}",
            f"summary.ilike.{pattern}",
            f"text.ilike.{pattern}",
            f"source.ilike.{pattern}",
            f"feed.ilike.{pattern}",
            f"author.ilike.{pattern}",
        ]
    )


def _apply_filters(params: dict, search=None, sentiment=None, category=None, event_id=None):
    _apply_search(params, search)

    sentiment_value = _normalize_sentiment(sentiment)
    if sentiment_value and sentiment_value != "all":
        params["sentiment"] = f"eq.{sentiment_value}"

    category_value = _normalize_category(category)
    if category_value and category_value != "all":
        params["category"] = f"eq.{category_value}"

    if event_id is not None:
        article_ids = list_article_ids_for_event(event_id)
        if not article_ids:
            params["id"] = "eq.-1"
            return
        params["id"] = f"in.({','.join(str(article_id) for article_id in article_ids)})"


def _fetch_articles(params: dict):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return [], 0

    try:
        resp = requests.get(
            _base_endpoint(),
            headers={
                **_auth_headers(),
                "Prefer": "count=exact",
            },
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list):
            rows = []
        total = _parse_total(resp.headers.get("Content-Range"), fallback=len(rows))
        return rows, total
    except Exception:
        return [], 0


def _fetch_rows_for_stats(search=None, category=None, event_id=None, limit=1000):
    if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
        return []

    rows = []
    page_size = max(1, min(int(limit or 1000), 200))
    offset = 0

    while True:
        params = {
            "select": "sentiment,category,article_category,insight_json,summary",
            "limit": str(page_size),
            "offset": str(offset),
            "order": "created_at.desc",
        }
        _apply_filters(params, search=search, category=category, event_id=event_id)
        try:
            resp = requests.get(
                _base_endpoint(),
                headers=_auth_headers(),
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not isinstance(batch, list) or not batch:
                break
            rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        except Exception:
            break

    return rows


def _list_top_items(values, limit=6):
    cleaned = []
    counts = Counter()
    display = {}
    for value in values:
        text = _normalize_text(value)
        if not text:
            continue
        key = text.lower()
        counts[key] += 1
        if key not in display:
            display[key] = text
    for key, count in counts.most_common(limit):
        cleaned.append({"text": display[key], "count": count})
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
        insight = row.get("insight_json") if isinstance(row.get("insight_json"), dict) else {}
        positive_feedback.extend(_normalize_feedback_list(insight.get("positive_feedback")))
        negative_feedback.extend(_normalize_feedback_list(insight.get("negative_feedback")))
        nice_to_have_features.extend(_normalize_feedback_list(insight.get("nice_to_have_features")))
        complaints.extend(_normalize_feedback_list(insight.get("complaints")))
        great_features.extend(_normalize_feedback_list(insight.get("great_features")))
        comfort_issues.extend(_normalize_feedback_list(insight.get("comfort_issues")))
        performance_feedback.extend(_normalize_feedback_list(insight.get("performance_feedback")))
        price_value_feedback.extend(_normalize_feedback_list(insight.get("price_value_feedback")))
        maintenance_reliability_feedback.extend(_normalize_feedback_list(insight.get("maintenance_reliability_feedback")))
        technology_feedback.extend(_normalize_feedback_list(insight.get("technology_feedback")))
        safety_feedback.extend(_normalize_feedback_list(insight.get("safety_feedback")))
        people_opinions.extend(_normalize_people_opinions(insight.get("people_opinions")))
        frequent_ideas.extend(_normalize_frequent_ideas(insight.get("frequent_ideas")))
        topic = _normalize_text(insight.get("topic") or row.get("title"))
        if topic:
            topics.append(topic)

    idea_counts = Counter()
    idea_display = {}
    idea_type = {}
    idea_category = {}
    for item in frequent_ideas:
        idea = _normalize_text(item.get("idea"))
        if not idea:
            continue
        key = idea.lower()
        idea_counts[key] += 1
        idea_display.setdefault(key, idea)
        idea_type.setdefault(key, item.get("type") or "issue")
        idea_category.setdefault(key, item.get("category") or "")

    frequent_ideas_rollup = [
        {
            "idea": idea_display[key],
            "type": idea_type.get(key, "issue"),
            "category": idea_category.get(key, ""),
            "frequency_estimate": count,
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

    return {
        "summary": summary,
        "topic": topics[0] if topics else "",
        "article_category_breakdown": _article_category_counts(rows),
        "overall_sentiment": _overall_sentiment(rows),
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


def list_articles(search=None, sentiment=None, category=None, event_id=None, limit=DEFAULT_LIMIT, offset=0, sort=DEFAULT_SORT):
    limit = _normalize_limit(limit)
    offset = _normalize_offset(offset)
    field, direction = _normalize_sort(sort)

    params = {
        "select": ARTICLES_SELECT,
        "limit": str(limit),
        "offset": str(offset),
        "order": f"{field}.{direction}",
    }
    _apply_filters(params, search=search, sentiment=sentiment, category=category, event_id=event_id)
    rows, total = _fetch_articles(params)
    return {
        "articles": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "sort": f"{field}.{direction}",
    }


def _count_articles(search=None, sentiment=None, category=None, event_id=None):
    params = {
        "select": "id",
        "limit": "1",
    }
    _apply_filters(params, search=search, sentiment=sentiment, category=category, event_id=event_id)
    _, total = _fetch_articles(params)
    return total


def get_article_stats(search=None, category=None, event_id=None):
    total = _count_articles(search=search, category=category, event_id=event_id)
    positive = _count_articles(search=search, sentiment="positive", category=category, event_id=event_id)
    negative = _count_articles(search=search, sentiment="negative", category=category, event_id=event_id)
    neutral = _count_articles(search=search, sentiment="neutral", category=category, event_id=event_id)
    rows = _fetch_rows_for_stats(search=search, category=category, event_id=event_id)

    return {
        "total": total,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "article_category_breakdown": _article_category_counts(rows),
        "insights": _topic_summary(rows),
    }
