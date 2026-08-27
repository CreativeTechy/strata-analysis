"""Sentiment/tone/topic rollups over a scope of articles - the dashboard's
stats cards and the article-analysis detail page's overall_tone. Builds on
articles_query (plain fetch) and articles_search (search-scoped fetch); this
is the top of the dependency chain, so nothing else in services/articles/
should need to import from here except articles_store.py's facade.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import config
from services.articles.articles_query import (
    ARTICLES_SELECT,
    BULK_PAGE_SIZE,
    _fetch_articles,
    _normalize_article_category,
    _normalize_sentiment,
    _normalize_text,
    _normalize_tone,
)
from services.articles.articles_search import search_results


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
            source_id = value.get("id")
            source_pipeline_run_id = value.get("pipeline_run_id")
            source_published = value.get("published")
        else:
            text = _normalize_text(value)
            source_url = ""
            source_title = ""
            source_id = None
            source_pipeline_run_id = None
            source_published = None
        if not text:
            continue
        key = text.lower()
        counts[key] += 1
        if key not in display:
            display[key] = text
        if source_url or source_title:
            sources.setdefault(key, [])
            source_entry = {
                "id": source_id,
                "url": source_url,
                "title": source_title or source_url,
                "pipeline_run_id": source_pipeline_run_id,
                "published": source_published,
            }
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


def _source_language_counts(rows):
    counts = Counter()
    for row in rows:
        language = str(row.get("source_language") or "").strip().lower() or "unknown"
        counts[language] += 1
    return [{"language": language, "count": count} for language, count in counts.most_common()]


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


def _demographic_sentiment_breakdown(rows, field):
    """Sentiment crosstab for one demographic dimension (region/gender/
    age_range) - each bucket's positive_pct/negative_pct is exactly the
    "50% of X are positive" stat these columns exist for. Reads the article's
    own rolled-up column (see analysis/aggregation.py's
    compute_dominant_demographics), not the per-opinion values."""
    buckets = defaultdict(Counter)
    for row in rows:
        value = _normalize_text(row.get(field)) or "unknown"
        buckets[value][_normalize_sentiment(row.get("sentiment"))] += 1

    breakdown = []
    for value, counts in buckets.items():
        total = sum(counts.values())
        breakdown.append({
            "value": value,
            "total": total,
            "positive": counts.get("positive", 0),
            "negative": counts.get("negative", 0),
            "neutral": counts.get("neutral", 0),
            "mixed": counts.get("mixed", 0),
            "positive_pct": round(counts.get("positive", 0) / total * 100, 1) if total else 0.0,
            "negative_pct": round(counts.get("negative", 0) / total * 100, 1) if total else 0.0,
        })
    breakdown.sort(key=lambda item: -item["total"])
    return breakdown


def _verified_breakdown(rows):
    """Verified/unverified article counts for the dashboard's trusted-source
    pie chart - see trusted_sources.py. A plain count, not a sentiment
    crosstab like _demographic_sentiment_breakdown, since `verified` is a
    boolean rather than a text bucket value."""
    verified_count = sum(1 for row in rows if row.get("verified"))
    total = len(rows)
    return [
        {"value": "verified", "total": verified_count},
        {"value": "unverified", "total": total - verified_count},
    ]


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
            "id": row.get("id"),
            "url": _normalize_text(row.get("url")),
            "title": _normalize_text(row.get("title")),
            "pipeline_run_id": row.get("pipeline_run_id"),
            "published": row.get("published"),
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
                "id": item.get("id"),
                "url": _normalize_text(item.get("url")),
                "title": _normalize_text(item.get("title")) or _normalize_text(item.get("url")),
                "pipeline_run_id": item.get("pipeline_run_id"),
                "published": item.get("published"),
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
        "language_breakdown": _source_language_counts(rows),
        "overall_sentiment": _overall_sentiment(rows),
        "overall_mood": _overall_mood_from_counts(article_tone_counts),
        "overall_tone": _group_overall_tone(article_tone_counts, writer_tone_counts),
        "writer_tone_breakdown": [{"tone": tone, "count": count} for tone, count in writer_tone_counts.most_common()],
        "article_tone_breakdown": [{"tone": tone, "count": count} for tone, count in article_tone_counts.most_common()],
        "region_breakdown": _demographic_sentiment_breakdown(rows, "region"),
        "gender_breakdown": _demographic_sentiment_breakdown(rows, "gender"),
        "age_range_breakdown": _demographic_sentiment_breakdown(rows, "age_range"),
        "segment_breakdown": _demographic_sentiment_breakdown(rows, "segment"),
        "verified_breakdown": _verified_breakdown(rows),
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


def _fetch_rows_for_stats(search=None, category=None, project_id=None, limit=1000, date_from=None, date_to=None):
    if not config.DATABASE_URL:
        return []

    rows = []
    total_cap = max(1, int(limit or 1000))
    page_size = min(total_cap, BULK_PAGE_SIZE)
    offset = 0

    while len(rows) < total_cap:
        want = min(page_size, total_cap - len(rows))
        batch, _ = _fetch_articles(
            limit=want,
            offset=offset,
            search=search,
            category=category,
            project_id=project_id,
            order="created_at.desc",
            select="id,url,title,sentiment,category,article_category,writer_tone,article_tone,region,gender,age_range,segment,verified,insight_json,summary,published,pipeline_run_id,source_language",
            date_from=date_from,
            date_to=date_to,
            max_limit=page_size,
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < want:
            break
        offset += len(batch)

    return rows[:total_cap]


def _count_articles(search=None, sentiment=None, category=None, project_id=None, date_from=None, date_to=None):
    search_text = _normalize_text(search)
    if search_text:
        _, total = search_results(
            search=search_text,
            sentiment=sentiment,
            category=category,
            project_id=project_id,
            date_from=date_from,
            date_to=date_to,
        )
        return total

    _, total = _fetch_articles(
        limit=1,
        offset=0,
        search=search,
        sentiment=sentiment,
        category=category,
        project_id=project_id,
        order="published.desc",
        select="id",
        date_from=date_from,
        date_to=date_to,
    )
    return total


def get_article_stats(search=None, category=None, project_id=None, date_from=None, date_to=None):
    """Sentiment/category/insight rollup for a scope, optionally bounded to a date window.

    date_from/date_to are ISO date or datetime strings compared against
    coalesce(published, created_at); either can be omitted for an open-ended
    bound. The response shape is unchanged from the unfiltered case so
    existing UI consumers keep working - the date window only narrows which
    articles are counted.
    """
    total = _count_articles(search=search, category=category, project_id=project_id, date_from=date_from, date_to=date_to)
    positive = _count_articles(search=search, sentiment="positive", category=category, project_id=project_id, date_from=date_from, date_to=date_to)
    negative = _count_articles(search=search, sentiment="negative", category=category, project_id=project_id, date_from=date_from, date_to=date_to)
    neutral = _count_articles(search=search, sentiment="neutral", category=category, project_id=project_id, date_from=date_from, date_to=date_to)
    mixed = _count_articles(search=search, sentiment="mixed", category=category, project_id=project_id, date_from=date_from, date_to=date_to)
    search_text = _normalize_text(search)
    if search_text:
        rows, _ = search_results(search=search_text, category=category, project_id=project_id, date_from=date_from, date_to=date_to)
    else:
        rows = _fetch_rows_for_stats(search=search, category=category, project_id=project_id, date_from=date_from, date_to=date_to)

    return {
        "total": total,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "mixed": mixed,
        "article_category_breakdown": _article_category_counts(rows),
        "insights": _topic_summary(rows),
    }
