"""Cross-article aggregation stage: rolls up per-article insight_json into a
project/batch-level summary (dominant topic/category/sentiment, top
feedback items, frequent-idea frequency counts, tone breakdowns).

Moved out of enrich.py (logic unchanged) so it's an explicit pipeline stage
rather than inline code in the orchestrator script. articles_store.py has
its own read-time version of this same rollup (_topic_summary) for querying
already-stored rows from Postgres - this module is the write-time version
that runs once per pipeline run, over the batch just enriched.
"""

from __future__ import annotations

from collections import Counter

from analysis import normalize

DEFAULT_CATEGORY = normalize.labels.DEFAULT_CATEGORY
DEFAULT_TONE = normalize.labels.DEFAULT_TONE


def compute_overall_tone(article_tone, writer_tone) -> str:
    """Deterministic overall_tone for a single article. Never guessed by the AI."""
    article_tone = normalize.normalize_tone(article_tone)
    writer_tone = normalize.normalize_tone(writer_tone)
    if article_tone == writer_tone:
        return article_tone
    if article_tone == DEFAULT_TONE and writer_tone != DEFAULT_TONE:
        return writer_tone
    if writer_tone == DEFAULT_TONE and article_tone != DEFAULT_TONE:
        return article_tone
    return "mixed"


def _group_overall_tone(article_tone_counts, writer_tone_counts) -> str:
    """Deterministic overall_tone for a collection of articles (project rollup).

    Prefers the most frequent non-neutral article_tone; falls back to
    writer_tone only as a tie-breaker/fallback; "mixed" on conflict.
    """
    non_neutral_article = [(tone, count) for tone, count in article_tone_counts.items() if tone != DEFAULT_TONE and count]
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

    non_neutral_writer = [(tone, count) for tone, count in writer_tone_counts.items() if tone != DEFAULT_TONE and count]
    if non_neutral_writer:
        top_count = max(count for _, count in non_neutral_writer)
        top_tones = {tone for tone, count in non_neutral_writer if count == top_count}
        if len(top_tones) == 1:
            return next(iter(top_tones))
        return "mixed"

    return DEFAULT_TONE


def _dedupe_key(value) -> str:
    return normalize.as_text(value).strip().lower()


def _top_items(values, limit=6) -> list:
    counts = Counter(_dedupe_key(value) for value in values if normalize.as_text(value))
    meta = {}
    for value in values:
        text = normalize.as_text(value)
        if not text:
            continue
        key = _dedupe_key(text)
        if key not in meta:
            meta[key] = text
    return [{"text": meta[key], "count": count} for key, count in counts.most_common(limit)]


def build_topic_insight(articles: list, topic_name: str = "") -> dict:
    """Build a rollup from a batch of already-enriched articles' insight_json."""
    if not articles:
        return {
            "topic": topic_name or "",
            "overall_sentiment": "neutral",
            "overall_mood": DEFAULT_TONE,
            "overall_tone": DEFAULT_TONE,
            "summary": "",
            "article_category_breakdown": [],
            "writer_tone_breakdown": [],
            "article_tone_breakdown": [],
            "positive_feedback": [],
            "negative_feedback": [],
            "nice_to_have_features": [],
            "complaints": [],
            "great_features": [],
            "comfort_issues": [],
            "performance_feedback": [],
            "price_value_feedback": [],
            "maintenance_reliability_feedback": [],
            "technology_feedback": [],
            "safety_feedback": [],
            "people_opinions": [],
            "frequent_ideas": [],
        }

    category_counts = Counter()
    sentiment_counts = Counter()
    writer_tone_counts = Counter()
    article_tone_counts = Counter()
    topic_counter = Counter()

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

    for article in articles:
        insight = article.get("insight_json")
        if not isinstance(insight, dict):
            insight = {}
        article_category = normalize.normalize_category(
            article.get("article_category") or insight.get("article_category") or article.get("category")
        )
        category_counts[article_category] += 1
        sentiment_counts[normalize.normalize_sentiment(article.get("sentiment") or insight.get("overall_sentiment"))] += 1
        writer_tone_counts[normalize.normalize_tone(article.get("writer_tone") or insight.get("writer_tone"))] += 1
        article_tone_counts[normalize.normalize_tone(article.get("article_tone") or insight.get("article_tone"))] += 1
        topic = normalize.as_text(article.get("topic") or insight.get("topic"))
        if topic:
            topic_counter[topic] += 1

        positive_feedback.extend(normalize.normalize_feedback_list(insight.get("positive_feedback")))
        negative_feedback.extend(normalize.normalize_feedback_list(insight.get("negative_feedback")))
        nice_to_have_features.extend(normalize.normalize_feedback_list(insight.get("nice_to_have_features")))
        complaints.extend(normalize.normalize_feedback_list(insight.get("complaints")))
        great_features.extend(normalize.normalize_feedback_list(insight.get("great_features")))
        comfort_issues.extend(normalize.normalize_feedback_list(insight.get("comfort_issues")))
        performance_feedback.extend(normalize.normalize_feedback_list(insight.get("performance_feedback")))
        price_value_feedback.extend(normalize.normalize_feedback_list(insight.get("price_value_feedback")))
        maintenance_reliability_feedback.extend(normalize.normalize_feedback_list(insight.get("maintenance_reliability_feedback")))
        technology_feedback.extend(normalize.normalize_feedback_list(insight.get("technology_feedback")))
        safety_feedback.extend(normalize.normalize_feedback_list(insight.get("safety_feedback")))
        people_opinions.extend(normalize.normalize_people_opinions(insight.get("people_opinions")))
        frequent_ideas.extend(normalize.normalize_frequent_ideas(insight.get("frequent_ideas")))

    idea_counts = Counter()
    idea_meta = {}
    for item in frequent_ideas:
        idea = normalize.as_text(item.get("idea"))
        if not idea:
            continue
        key = _dedupe_key(idea)
        idea_counts[key] += 1
        if key not in idea_meta:
            idea_meta[key] = {
                "idea": idea,
                "type": item.get("type") if item.get("type") in {"complaint", "praise", "suggestion", "issue"} else "issue",
                "category": normalize.as_text(item.get("category")),
            }

    frequent_ideas_rollup = [
        {**idea_meta[key], "frequency_estimate": count}
        for key, count in idea_counts.most_common()
    ]

    positive_items = _top_items(positive_feedback + great_features)
    negative_items = _top_items(negative_feedback + complaints + comfort_issues)
    request_items = _top_items(nice_to_have_features)

    dominant_topic = topic_counter.most_common(1)[0][0] if topic_counter else topic_name
    dominant_category = category_counts.most_common(1)[0][0] if category_counts else DEFAULT_CATEGORY
    if sentiment_counts["negative"] > sentiment_counts["positive"] and sentiment_counts["negative"] >= sentiment_counts["neutral"]:
        overall_sentiment = "negative"
    elif sentiment_counts["positive"] > sentiment_counts["negative"] and sentiment_counts["positive"] >= sentiment_counts["neutral"]:
        overall_sentiment = "positive"
    elif sentiment_counts["positive"] and sentiment_counts["negative"]:
        overall_sentiment = "mixed"
    else:
        overall_sentiment = "neutral"

    overall_mood = article_tone_counts.most_common(1)[0][0] if article_tone_counts else DEFAULT_TONE
    overall_tone = _group_overall_tone(article_tone_counts, writer_tone_counts)

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
        "topic": dominant_topic,
        "article_category": dominant_category,
        "overall_sentiment": overall_sentiment,
        "overall_mood": overall_mood,
        "overall_tone": overall_tone,
        "summary": summary,
        "article_category_breakdown": [
            {"category": category, "count": count}
            for category, count in category_counts.most_common()
        ],
        "writer_tone_breakdown": [
            {"tone": tone, "count": count}
            for tone, count in writer_tone_counts.most_common()
        ],
        "article_tone_breakdown": [
            {"tone": tone, "count": count}
            for tone, count in article_tone_counts.most_common()
        ],
        "positive_feedback": positive_items,
        "negative_feedback": negative_items,
        "nice_to_have_features": request_items,
        "complaints": _top_items(complaints),
        "great_features": _top_items(great_features),
        "comfort_issues": _top_items(comfort_issues),
        "performance_feedback": _top_items(performance_feedback),
        "price_value_feedback": _top_items(price_value_feedback),
        "maintenance_reliability_feedback": _top_items(maintenance_reliability_feedback),
        "technology_feedback": _top_items(technology_feedback),
        "safety_feedback": _top_items(safety_feedback),
        "people_opinions": people_opinions[:10],
        "frequent_ideas": frequent_ideas_rollup[:12],
    }
