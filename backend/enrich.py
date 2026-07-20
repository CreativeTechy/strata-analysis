"""The ENRICHER stage: clean scraped articles, tag them with AI,
and hand them to the saver (store.save_articles). Reads articles.json, writes
enriched_articles.json, then upserts to local PostgreSQL.
"""

import json
import os
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import config
from embeddings import build_article_embedding_text, get_embedding
from projects_store import get_project
from llm_client import chat_completion
from pipeline_runs import update_pipeline_run
from store import save_articles

MIN_TEXT_LENGTH = 200
PROMPT_VERSION = "2026-07-15"
MODEL_NAME = config.OPENAI_CHAT_MODEL
VALID_SENTIMENTS = {"positive", "negative", "mixed", "neutral"}
VALID_CATEGORIES = {
    "review",
    "comparison",
    "complaint",
    "news",
    "ownership_experience",
    "buying_guide",
    "general_article",
}
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
STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage"
PIPELINE_RUN_ID = os.environ.get("PIPELINE_RUN_ID", "").strip()
PIPELINE_PROJECT_ID = os.environ.get("PIPELINE_PROJECT_ID", "").strip()
INPUT_FILE = Path(os.environ.get("PIPELINE_RAW_FILE", "articles.json"))
OUTPUT_FILE = Path(os.environ.get("PIPELINE_ENRICHED_FILE", "enriched_articles.json"))
PIPELINE_STATS_FILE = Path(os.environ.get("PIPELINE_STATS_FILE", "")) if os.environ.get("PIPELINE_STATS_FILE") else None

# Used when AI enrichment fails so the pipeline still produces
# rows that satisfy the local PostgreSQL schema instead of crashing.
DEFAULT_ENRICHMENT = {
    "topic": "",
    "article_category": "general_article",
    "overall_sentiment": "neutral",
    "writer_tone": "neutral",
    "article_tone": "neutral",
    "overall_tone": "neutral",
    "summary": "",
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
    "entities": [],
    "organizations": [],
    "topics": [],
    "key_points": [],
    "risks": [],
    "opportunities": [],
    "car_models": [],
    "brands": [],
    "sentiment": "neutral",
    "category": "general_article",
    "relevance_score": 0,
    "analysis_model": MODEL_NAME,
    "analysis_prompt_version": PROMPT_VERSION,
    "analyzed_at": "",
    "insight_json": {},
    "embedding_json": [],
    "embedding_model": "",
    "embedding_source": "",
    "embedded_at": "",
}


def _load_project_context():
    if not PIPELINE_PROJECT_ID:
        return ""
    try:
        project = get_project(int(PIPELINE_PROJECT_ID))
    except Exception:
        project = None
    if not project:
        return ""

    parts = []
    name = (project.get("name") or "").strip()
    if name:
        parts.append(f"Name: {name}")
    status = (project.get("status") or "").strip()
    if status:
        parts.append(f"Status: {status}")
    start_date = project.get("start_date")
    if start_date:
        parts.append(f"Start date: {start_date}")
    end_date = project.get("end_date")
    if end_date:
        parts.append(f"End date: {end_date}")
    location = (project.get("location") or "").strip()
    if location:
        parts.append(f"Location: {location}")
    location_type = (project.get("location_type") or "").strip()
    if location_type:
        parts.append(f"Location type: {location_type}")
    first_run_at = project.get("first_run_at")
    if first_run_at:
        parts.append(f"First run at: {first_run_at}")
    target_audience = (project.get("target_audience") or "").strip()
    if target_audience:
        parts.append(f"Target audience: {target_audience}")
    hashtags = project.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = [hashtags]
    hashtags = [str(item).strip() for item in hashtags if str(item).strip()]
    if hashtags:
        parts.append(f"Hashtags: {', '.join(hashtags)}")
    keywords = project.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [str(item).strip() for item in keywords if str(item).strip()]
    if keywords:
        parts.append(f"Keywords: {', '.join(keywords)}")
    description = (project.get("description") or "").strip()
    if description:
        parts.append(f"Description: {description}")
    return "\n".join(parts)


def _load_project():
    if not PIPELINE_PROJECT_ID:
        return None
    try:
        return get_project(int(PIPELINE_PROJECT_ID))
    except Exception:
        return None


def _coerce_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        return datetime.fromisoformat(text).date()
    except Exception:
        pass

    try:
        return parsedate_to_datetime(text).date()
    except Exception:
        pass

    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _article_published_date(article):
    if not isinstance(article, dict):
        return None

    for key in ("published_at", "published"):
        published = _coerce_date(article.get(key))
        if published:
            return published
    return None


def _project_date_window(project):
    if not isinstance(project, dict):
        return None, None
    return _coerce_date(project.get("start_date")), _coerce_date(project.get("end_date"))


def _article_matches_project_window(article, project):
    article_date = _article_published_date(article)
    if article_date is None:
        return True

    start_date, end_date = _project_date_window(project)
    if start_date and article_date < start_date:
        return False
    if end_date and article_date > end_date:
        return False
    return True


def clean_articles(articles):
    seen_urls = set()
    cleaned = []
    for a in articles:
        url = a.get("url", "")
        text = a.get("text", "")
        if url in seen_urls:
            continue
        if len(text) < MIN_TEXT_LENGTH:
            continue
        if not a.get("title"):
            continue
        seen_urls.add(url)
        cleaned.append(a)
    print(f"Cleaned: {len(articles)} -> {len(cleaned)} articles")
    return cleaned


def _load_prompt_template():
    prompt_file = STORAGE_DIR / "enrichment_prompt.txt"
    try:
        return prompt_file.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are analyzing ONE scraped article.\n"
            "Use ONLY the article content.\n"
            "Return ONLY valid JSON with the exact structure requested.\n"
            "Article title:\n{title}\n\nArticle text:\n{text}"
        )


def _strip_code_fences(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3]
    return raw.strip()


def _as_list(value):
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
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _as_text(value):
    return str(value).strip() if value is not None else ""


def _normalize_category(value):
    category = _as_text(value).lower()
    return category if category in VALID_CATEGORIES else "general_article"


def _normalize_sentiment(value):
    sentiment = _as_text(value).lower()
    return sentiment if sentiment in VALID_SENTIMENTS else "neutral"


def _normalize_tone(value):
    tone = _as_text(value).lower()
    return tone if tone in VALID_TONES else "neutral"


def _compute_overall_tone(article_tone, writer_tone):
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


def _normalize_feedback_list(value):
    return _as_list(value)


def _coerce_frequency_estimate(value):
    try:
        return max(1, int(float(value)))
    except Exception:
        return 1


def _normalize_people_opinions(value):
    opinions = []
    if not isinstance(value, list):
        return opinions
    for item in value:
        if not isinstance(item, dict):
            text = _as_text(item)
            if text:
                opinions.append({
                    "opinion": text,
                    "sentiment": "neutral",
                    "category": "",
                })
            continue
        opinion = _as_text(item.get("opinion"))
        if not opinion:
            continue
        opinions.append({
            "opinion": opinion,
            "sentiment": _normalize_sentiment(item.get("sentiment")),
            "category": _as_text(item.get("category")),
        })
    deduped = []
    seen = set()
    for item in opinions:
        key = (item["opinion"].lower(), item["sentiment"], item["category"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_frequent_ideas(value):
    ideas = []
    if not isinstance(value, list):
        return ideas
    for item in value:
        if isinstance(item, dict):
            idea = _as_text(item.get("idea"))
            if not idea:
                continue
            ideas.append({
                "idea": idea,
                "type": _as_text(item.get("type")).lower() if _as_text(item.get("type")).lower() in {"complaint", "praise", "suggestion", "issue"} else "issue",
                "category": _as_text(item.get("category")),
                "frequency_estimate": _coerce_frequency_estimate(item.get("frequency_estimate", 1)),
            })
        else:
            idea = _as_text(item)
            if idea:
                ideas.append({
                    "idea": idea,
                    "type": "issue",
                    "category": "",
                    "frequency_estimate": 1,
                })
    deduped = []
    seen = set()
    for item in ideas:
        key = (item["idea"].lower(), item["type"], item["category"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_relevance_score(value):
    try:
        score = float(value)
    except Exception:
        return 0
    return max(0, min(score, 10))


def _validate_enrichment(payload):
    if not isinstance(payload, dict):
        return None

    summary = _as_text(payload.get("summary"))
    if not summary:
        return None

    article_category = _normalize_category(payload.get("article_category") or payload.get("category"))
    sentiment = _normalize_sentiment(payload.get("overall_sentiment") or payload.get("sentiment"))
    if sentiment == "neutral" and article_category in {"complaint"}:
        sentiment = "negative"

    writer_tone = _normalize_tone(payload.get("writer_tone"))
    article_tone = _normalize_tone(payload.get("article_tone"))
    overall_tone = _compute_overall_tone(article_tone, writer_tone)

    organizations = _as_list(payload.get("organizations") or payload.get("brands"))
    entities = _as_list(payload.get("entities") or payload.get("car_models"))
    topics = _as_list(payload.get("topics"))
    key_points = _as_list(payload.get("key_points"))
    risks = _as_list(payload.get("risks"))
    opportunities = _as_list(payload.get("opportunities"))
    positive_feedback = _normalize_feedback_list(payload.get("positive_feedback"))
    negative_feedback = _normalize_feedback_list(payload.get("negative_feedback"))
    nice_to_have_features = _normalize_feedback_list(payload.get("nice_to_have_features"))
    complaints = _normalize_feedback_list(payload.get("complaints"))
    great_features = _normalize_feedback_list(payload.get("great_features"))
    comfort_issues = _normalize_feedback_list(payload.get("comfort_issues"))
    performance_feedback = _normalize_feedback_list(payload.get("performance_feedback"))
    price_value_feedback = _normalize_feedback_list(payload.get("price_value_feedback"))
    maintenance_reliability_feedback = _normalize_feedback_list(payload.get("maintenance_reliability_feedback"))
    technology_feedback = _normalize_feedback_list(payload.get("technology_feedback"))
    safety_feedback = _normalize_feedback_list(payload.get("safety_feedback"))
    people_opinions = _normalize_people_opinions(payload.get("people_opinions"))
    frequent_ideas = _normalize_frequent_ideas(payload.get("frequent_ideas"))

    insight_json = {
        "topic": _as_text(payload.get("topic")),
        "article_category": article_category,
        "overall_sentiment": sentiment,
        "writer_tone": writer_tone,
        "article_tone": article_tone,
        "overall_tone": overall_tone,
        "summary": summary,
        "positive_feedback": positive_feedback,
        "negative_feedback": negative_feedback,
        "nice_to_have_features": nice_to_have_features,
        "complaints": complaints,
        "great_features": great_features,
        "comfort_issues": comfort_issues,
        "performance_feedback": performance_feedback,
        "price_value_feedback": price_value_feedback,
        "maintenance_reliability_feedback": maintenance_reliability_feedback,
        "technology_feedback": technology_feedback,
        "safety_feedback": safety_feedback,
        "people_opinions": people_opinions,
        "frequent_ideas": frequent_ideas,
    }

    category = article_category

    analyzed_at = _as_text(payload.get("analyzed_at"))
    if not analyzed_at:
        analyzed_at = datetime.now(timezone.utc).isoformat()

    return {
        "topic": insight_json["topic"],
        "article_category": article_category,
        "overall_sentiment": sentiment,
        "writer_tone": writer_tone,
        "article_tone": article_tone,
        "overall_tone": overall_tone,
        "summary": summary,
        "positive_feedback": positive_feedback,
        "negative_feedback": negative_feedback,
        "nice_to_have_features": nice_to_have_features,
        "complaints": complaints,
        "great_features": great_features,
        "comfort_issues": comfort_issues,
        "performance_feedback": performance_feedback,
        "price_value_feedback": price_value_feedback,
        "maintenance_reliability_feedback": maintenance_reliability_feedback,
        "technology_feedback": technology_feedback,
        "safety_feedback": safety_feedback,
        "people_opinions": people_opinions,
        "frequent_ideas": frequent_ideas,
        "entities": entities,
        "organizations": organizations,
        "topics": topics,
        "key_points": key_points,
        "risks": risks,
        "opportunities": opportunities,
        "car_models": entities,
        "brands": organizations,
        "sentiment": sentiment,
        "category": category,
        "relevance_score": _normalize_relevance_score(payload.get("relevance_score", 0)),
        "analysis_model": _as_text(payload.get("analysis_model")) or MODEL_NAME,
        "analysis_prompt_version": _as_text(payload.get("analysis_prompt_version")) or PROMPT_VERSION,
        "analyzed_at": analyzed_at,
        "insight_json": insight_json,
        "embedding_json": _as_list(payload.get("embedding_json")),
        "embedding_model": _as_text(payload.get("embedding_model")),
        "embedding_source": _as_text(payload.get("embedding_source")),
        "embedded_at": _as_text(payload.get("embedded_at")),
    }


def _dedupe_key(value):
    return _as_text(value).strip().lower()


def _merge_unique_texts(*lists):
    merged = []
    seen = set()
    for values in lists:
        for value in values or []:
            text = _as_text(value)
            if not text:
                continue
            key = _dedupe_key(text)
            if key in seen:
                continue
            seen.add(key)
            merged.append(text)
    return merged


def _merge_feedback_items(items_by_key):
    merged = []
    seen = set()
    for item in items_by_key:
        if not isinstance(item, dict):
            continue
        text = _as_text(item.get("idea") or item.get("opinion") or item.get("feedback") or item.get("text"))
        if not text:
            continue
        category = _as_text(item.get("category"))
        type_value = _as_text(item.get("type")).lower()
        sentiment = _normalize_sentiment(item.get("sentiment"))
        key = (_dedupe_key(text), category.lower(), type_value, sentiment)
        if key in seen:
            continue
        seen.add(key)
        merged.append({
            "text": text,
            "category": category,
            "type": type_value,
            "sentiment": sentiment,
        })
    return merged


def build_topic_insight(articles, topic_name=""):
    """Build a simple rollup from article-level insight JSON."""
    if not articles:
        return {
            "topic": topic_name or "",
            "overall_sentiment": "neutral",
            "overall_mood": "neutral",
            "overall_tone": "neutral",
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
        article_category = _normalize_category(article.get("article_category") or insight.get("article_category") or article.get("category"))
        category_counts[article_category] += 1
        sentiment_counts[_normalize_sentiment(article.get("sentiment") or insight.get("overall_sentiment"))] += 1
        writer_tone_counts[_normalize_tone(article.get("writer_tone") or insight.get("writer_tone"))] += 1
        article_tone_counts[_normalize_tone(article.get("article_tone") or insight.get("article_tone"))] += 1
        topic = _as_text(article.get("topic") or insight.get("topic"))
        if topic:
            topic_counter[topic] += 1

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

    merged_feedback = _merge_feedback_items([])
    idea_counts = Counter()
    idea_meta = {}
    for item in frequent_ideas:
        idea = _as_text(item.get("idea"))
        if not idea:
            continue
        key = _dedupe_key(idea)
        idea_counts[key] += 1
        if key not in idea_meta:
            idea_meta[key] = {
                "idea": idea,
                "type": _as_text(item.get("type")).lower() if _as_text(item.get("type")).lower() in {"complaint", "praise", "suggestion", "issue"} else "issue",
                "category": _as_text(item.get("category")),
            }

    frequent_ideas_rollup = [
        {**idea_meta[key], "frequency_estimate": count}
        for key, count in idea_counts.most_common()
    ]

    def _top_items(values, limit=6):
        counts = Counter(_dedupe_key(value) for value in values if _as_text(value))
        meta = {}
        for value in values:
            text = _as_text(value)
            if not text:
                continue
            key = _dedupe_key(text)
            if key not in meta:
                meta[key] = text
        return [
            {"text": meta[key], "count": count}
            for key, count in counts.most_common(limit)
        ]

    positive_items = _top_items(positive_feedback + great_features)
    negative_items = _top_items(negative_feedback + complaints + comfort_issues)
    request_items = _top_items(nice_to_have_features)

    dominant_topic = topic_counter.most_common(1)[0][0] if topic_counter else topic_name
    dominant_category = category_counts.most_common(1)[0][0] if category_counts else "general_article"
    if sentiment_counts["negative"] > sentiment_counts["positive"] and sentiment_counts["negative"] >= sentiment_counts["neutral"]:
        overall_sentiment = "negative"
    elif sentiment_counts["positive"] > sentiment_counts["negative"] and sentiment_counts["positive"] >= sentiment_counts["neutral"]:
        overall_sentiment = "positive"
    elif sentiment_counts["positive"] and sentiment_counts["negative"]:
        overall_sentiment = "mixed"
    else:
        overall_sentiment = "neutral"

    overall_mood = article_tone_counts.most_common(1)[0][0] if article_tone_counts else "neutral"
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


def enrich_article(article, project_context=""):
    title = article.get("title", "")
    text = article.get("text", "")[:5000]
    prompt = (
        _load_prompt_template()
        .replace("{title}", title)
        .replace("{text}", text)
    )
    if project_context:
        prompt = f"{prompt}\n\nProject context:\n{project_context}\n\nUse this context only to help interpret the article. Do not invent facts."

    try:
        raw = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            model=MODEL_NAME,
            temperature=0.0,
            max_tokens=900,
            timeout=30,
        )
        parsed = json.loads(_strip_code_fences(raw))
        validated = _validate_enrichment(parsed)
        if validated is None:
            raise ValueError("Local LLM returned JSON that did not match the enrichment schema")
        embedding_text = build_article_embedding_text(article, validated)
        embedding = get_embedding(embedding_text)
        if embedding:
            validated.update(embedding)
        return validated
    except Exception as e:
        print(f"  Enrichment error for '{title[:50]}': {e}")
        return None


def write_output(articles):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(articles)} articles to {OUTPUT_FILE}")


def write_pipeline_stats(stats):
    if not PIPELINE_STATS_FILE:
        return
    PIPELINE_STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PIPELINE_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"Wrote pipeline stats to {PIPELINE_STATS_FILE.name}")


def push_run_progress(stats, stage, message, final=False):
    if not PIPELINE_RUN_ID:
        return
    try:
        update_pipeline_run(
            PIPELINE_RUN_ID,
            status="success" if final else "running",
            stage=stage,
            message=message,
            articles_scraped=int(stats.get("articles_scraped") or 0),
            articles_cleaned=int(stats.get("articles_cleaned") or 0),
            articles_saved=int(stats.get("articles_saved") or 0),
        )
    except Exception as e:
        print(f"Pipeline progress update failed: {e}")


def main():
    print(f"Loading articles from {INPUT_FILE}...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_articles = json.load(f)

    articles = clean_articles(raw_articles)
    stats = {
        "articles_scraped": len(raw_articles),
        "articles_cleaned": len(articles),
        "articles_enriched": 0,
        "articles_saved": 0,
    }

    push_run_progress(
        stats,
        stage="enrich",
        message="Scrape complete. Cleaning articles...",
    )

    if not articles:
        print("No articles to process after cleaning.")
        write_output([])
        write_pipeline_stats(stats)
        push_run_progress(
            stats,
            stage="done",
            message="No articles left after cleaning.",
            final=True,
        )
        return

    project = _load_project()
    project_context = _load_project_context()
    project_name = ""
    if project_context:
        for line in project_context.splitlines():
            if line.startswith("Name: "):
                project_name = line.replace("Name: ", "", 1).strip()
                break

    if project:
        matching_articles = [article for article in articles if _article_matches_project_window(article, project)]
    else:
        matching_articles = articles

    filtered_out = len(articles) - len(matching_articles)
    if filtered_out:
        print(f"Filtered out {filtered_out} articles outside the project date window.")
    articles = matching_articles

    enriched = []
    for idx, article in enumerate(articles):
        title = article.get("title", "")[:60]
        progress = {
            **stats,
            "articles_cleaned": idx + 1,
            "articles_enriched": len(enriched),
        }
        push_run_progress(
            progress,
            stage="enrich",
            message=f"Cleaning articles {idx + 1}/{len(articles)}...",
        )
        print(f"[{idx + 1}/{len(articles)}] Enriching: {title}")
        enrichment = enrich_article(article, project_context=project_context)
        if enrichment is None:
            enrichment = dict(DEFAULT_ENRICHMENT)
        time.sleep(0.5)
        if not enrichment.get("embedding_json"):
            embedding_text = build_article_embedding_text(article, enrichment)
            embedding = get_embedding(embedding_text)
            if embedding:
                enrichment.update(embedding)
        if not enrichment.get("analyzed_at"):
            enrichment["analyzed_at"] = datetime.now(timezone.utc).isoformat()
        enriched.append({**article, **enrichment})

    topic_insight = build_topic_insight(enriched, topic_name=project_name or "general")
    for article in enriched:
        if not article.get("insight_json"):
            article["insight_json"] = {
                "topic": article.get("topic", ""),
                "article_category": article.get("article_category", article.get("category", "general_article")),
                "overall_sentiment": article.get("overall_sentiment", article.get("sentiment", "neutral")),
                "writer_tone": article.get("writer_tone", "neutral"),
                "article_tone": article.get("article_tone", "neutral"),
                "overall_tone": article.get("overall_tone") or _compute_overall_tone(
                    article.get("article_tone"), article.get("writer_tone")
                ),
                "summary": article.get("summary", ""),
            }

    stats["articles_enriched"] = len(enriched)
    print(f"\nEnriched {len(enriched)} articles successfully.")
    print(f"Topic insight summary: {topic_insight.get('summary', '')[:120]}")

    push_run_progress(
        stats,
        stage="enrich",
        message="Enrichment complete. Saving articles...",
    )

    write_output(enriched)

    if enriched:
        print("Saving to local PostgreSQL...")
        stats["articles_saved"] = save_articles(enriched)
        print("Done.")
        push_run_progress(
            stats,
            stage="done",
            message="Pipeline complete.",
            final=True,
        )

    write_pipeline_stats(stats)


if __name__ == "__main__":
    main()
