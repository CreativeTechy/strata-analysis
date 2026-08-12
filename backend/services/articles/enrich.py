"""The ENRICHER stage: clean scraped articles, run them through the modular
analysis pipeline (backend/analysis/), and hand them to the saver
(store.save_articles). Reads articles.json, writes enriched_articles.json,
then upserts to local PostgreSQL.
"""

import json
import os
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import config
from analysis.aggregation import build_topic_insight, compute_overall_tone
from analysis.orchestrator import PIPELINE_VERSION, analyze_article, describe_models
from content_guard import is_blocked_article
from embeddings import build_article_embedding_text, get_embedding
from services.projects.projects_store import get_project
from services.pipeline.pipeline_runs import update_pipeline_run, upsert_pipeline_run_source_stats
from services.pipeline.source_diagnostics import build_fetch_note, load_source_diagnostics
from services.articles.store import get_existing_enrichment, save_articles

MIN_TEXT_LENGTH = 200
PIPELINE_RUN_ID = os.environ.get("PIPELINE_RUN_ID", "").strip()
PIPELINE_PROJECT_ID = os.environ.get("PIPELINE_PROJECT_ID", "").strip()
PIPELINE_WORKDIR = os.environ.get("PIPELINE_WORKDIR", "").strip()
INPUT_FILE = Path(os.environ.get("PIPELINE_RAW_FILE", "articles.json"))
OUTPUT_FILE = Path(os.environ.get("PIPELINE_ENRICHED_FILE", "enriched_articles.json"))
PIPELINE_STATS_FILE = Path(os.environ.get("PIPELINE_STATS_FILE", "")) if os.environ.get("PIPELINE_STATS_FILE") else None

# Used only when enrich_article()'s own exception guard trips - i.e. the
# analysis pipeline crashed somewhere no stage's own error handling caught.
# In the ordinary "structured extraction failed validation" case,
# analyze_article() already returns neutral content plus a real
# analysis_status="failed"/analysis_error - this is the last-resort fallback
# below that.
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
    "analysis_model": describe_models(),
    "analysis_prompt_version": PIPELINE_VERSION,
    "analyzed_at": "",
    "insight_json": {},
    "embedding_json": [],
    "embedding_model": "",
    "embedding_source": "",
    "embedded_at": "",
    "sentiment_score": 0.0,
    "sentiment_low_confidence": True,
    "sentiment_model": None,
    "category_confidence": 0.0,
    "writer_tone_confidence": 0.0,
    "article_tone_confidence": 0.0,
    "classification_model": None,
    "extraction_model": None,
    "analysis_pipeline_version": PIPELINE_VERSION,
    "source_language": None,
    "source_language_confidence": 0.0,
    "analysis_status": "failed",
    "analysis_error": "pipeline_crashed",
    "analysis_started_at": None,
    "analysis_finished_at": None,
    "analysis_attempt_count": 0,
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


def _source_key(article):
    return (article.get("source_name") or article.get("source") or "unknown").strip() or "unknown"


def _reuse_existing_enrichment(article, existing_map):
    """An already-stored, successful analysis for this article's URL, if one
    exists AND was produced by today's PIPELINE_VERSION - None otherwise, so
    a pipeline/prompt upgrade doesn't leave old articles stuck reusing
    stale-version analysis forever (see config.SKIP_EXISTING_ARTICLES)."""
    if not existing_map:
        return None
    existing = existing_map.get(article.get("url"))
    if not existing or existing.get("analysis_pipeline_version") != PIPELINE_VERSION:
        return None
    return existing


def _set_run_timestamps(**fields):
    if not PIPELINE_RUN_ID:
        return
    try:
        update_pipeline_run(PIPELINE_RUN_ID, **fields)
    except Exception as e:
        print(f"Pipeline timestamp update failed: {e}")


def _persist_source_stats(scraped, removed, date_filtered, skipped_existing, kept, enriched, saved):
    if not PIPELINE_RUN_ID:
        return

    # Fetch-time diagnostics the spider recorded per configured source (was it
    # blocked/404/DNS-failed, or did it just return nothing) - see
    # scraper/spiders/source_rss.py's closed() and source_diagnostics.py.
    # Included in `sources` below so a source with 0 scraped items (which
    # never appears in scraped/removed/date_filtered/kept/enriched/saved)
    # still gets a row instead of silently having no per-source data at all.
    diagnostics_by_source = {
        entry.get("source_name"): entry
        for entry in load_source_diagnostics(PIPELINE_WORKDIR)
        if entry.get("source_name")
    }

    sources = (
        set(scraped) | set(removed) | set(date_filtered) | set(skipped_existing)
        | set(kept) | set(enriched) | set(saved) | set(diagnostics_by_source)
    )
    source_stats = {}
    for source in sources:
        removed_counts = removed.get(source) or {}
        scraped_count = scraped.get(source, 0)
        diagnostic = diagnostics_by_source.get(source)
        source_stats[source] = {
            "source_url": (diagnostic or {}).get("source_url"),
            "scraped": scraped_count,
            "duplicate": removed_counts.get("duplicate", 0),
            "blocked": removed_counts.get("blocked", 0),
            "date_filtered": date_filtered.get(source, 0),
            "skipped_existing": skipped_existing.get(source, 0),
            "kept": kept.get(source, 0),
            "enriched": enriched.get(source, 0),
            "saved": saved.get(source, 0),
            "http_status": (diagnostic or {}).get("http_status"),
            "network_blocked": bool((diagnostic or {}).get("network_blocked")),
            "fetch_note": build_fetch_note(diagnostic, scraped_count),
        }
    upsert_pipeline_run_source_stats(PIPELINE_RUN_ID, source_stats)


def clean_articles(articles, seen_urls=None):
    """Returns (cleaned_articles, removed_counts_by_source), the latter tallying
    why an article didn't make it past dedup/quality filtering (see
    pipeline_run_sources - "duplicate" and "blocked" buckets).

    `seen_urls` defaults to a fresh set (this call's own batch only, the
    original behavior). Pass a set you own across repeated single-article
    calls - see scraper/pipelines.py's streaming pipeline - to dedup across
    the whole run instead of just within one call's batch."""
    if seen_urls is None:
        seen_urls = set()
    cleaned = []
    removed_by_source = defaultdict(lambda: {"duplicate": 0, "blocked": 0})
    for a in articles:
        source = _source_key(a)
        url = a.get("url", "")
        text = a.get("text", "")
        if url in seen_urls:
            removed_by_source[source]["duplicate"] += 1
            continue
        # Secondary safeguard: the scraper already rejects Google consent/search
        # pages (see content_guard.py), but this also catches rows coming from
        # an articles.json produced before that guard existed.
        if len(text) < MIN_TEXT_LENGTH or not a.get("title") or is_blocked_article(url, a.get("title")):
            removed_by_source[source]["blocked"] += 1
            continue
        seen_urls.add(url)
        cleaned.append(a)
    print(f"Cleaned: {len(articles)} -> {len(cleaned)} articles")
    return cleaned, removed_by_source


def enrich_article(article, project_context=""):
    """Run the modular analysis pipeline (analysis/orchestrator.py) for one
    article. analyze_article() always returns a dict - even a structured
    extraction failure comes back as neutral content plus a real
    analysis_status="failed"/analysis_error, not None. This only returns
    None if something escapes every stage's own error handling (a bug, not
    an expected failure mode); the caller falls back to DEFAULT_ENRICHMENT."""
    title = article.get("title", "")
    try:
        result = analyze_article(article, project_context=project_context)
        if result.get("analysis_status") != "success":
            print(f"  Enrichment issue for '{title[:50]}': {result.get('analysis_error')}")
        return result
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
    clean_started_at = datetime.now(timezone.utc).isoformat()
    _set_run_timestamps(clean_started_at=clean_started_at)

    print(f"Loading articles from {INPUT_FILE}...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_articles = json.load(f)

    scraped_by_source = Counter(_source_key(article) for article in raw_articles)
    articles, removed_by_source = clean_articles(raw_articles)
    stats = {
        "articles_scraped": len(raw_articles),
        "articles_cleaned": len(articles),
        "articles_enriched": 0,
        "articles_saved": 0,
    }

    push_run_progress(
        stats,
        stage="clean",
        message="Scrape complete. Cleaning articles...",
    )

    if not articles:
        print("No articles to process after cleaning.")
        write_output([])
        write_pipeline_stats(stats)
        clean_finished_at = datetime.now(timezone.utc).isoformat()
        _set_run_timestamps(
            clean_finished_at=clean_finished_at,
            enrich_started_at=clean_finished_at,
            enrich_finished_at=clean_finished_at,
        )
        _persist_source_stats(scraped_by_source, removed_by_source, {}, {}, {}, {}, {})
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

    date_filtered_by_source = Counter()
    if project:
        matching_articles = []
        for article in articles:
            if _article_matches_project_window(article, project):
                matching_articles.append(article)
            else:
                date_filtered_by_source[_source_key(article)] += 1
    else:
        matching_articles = articles

    filtered_out = len(articles) - len(matching_articles)
    if filtered_out:
        print(f"Filtered out {filtered_out} articles outside the project date window.")
    articles = matching_articles
    kept_by_source = Counter(_source_key(article) for article in articles)

    clean_finished_at = datetime.now(timezone.utc).isoformat()
    _set_run_timestamps(
        clean_finished_at=clean_finished_at,
        enrich_started_at=clean_finished_at,
        stage="enrich",
        message="Cleaning complete. Enriching articles...",
    )

    existing_by_url = get_existing_enrichment([a.get("url") for a in articles]) if config.SKIP_EXISTING_ARTICLES else {}

    enriched = []
    enriched_by_source = Counter()
    skipped_existing_by_source = Counter()
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
            message=f"Enriching articles {idx + 1}/{len(articles)}...",
        )

        reused = _reuse_existing_enrichment(article, existing_by_url)
        if reused is not None:
            print(f"[{idx + 1}/{len(articles)}] Already enriched, reusing: {title}")
            skipped_existing_by_source[_source_key(article)] += 1
            enriched.append({**article, **reused})
            continue

        print(f"[{idx + 1}/{len(articles)}] Enriching: {title}")
        enrichment = enrich_article(article, project_context=project_context)
        if enrichment is None:
            enrichment = dict(DEFAULT_ENRICHMENT)
        if enrichment.get("analysis_status") == "success":
            enriched_by_source[_source_key(article)] += 1
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
                "overall_tone": article.get("overall_tone") or compute_overall_tone(
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

    saved_by_source = {}
    if enriched:
        print("Saving to local PostgreSQL...")
        stats["articles_saved"], saved_by_source = save_articles(enriched)
        print("Done.")
        push_run_progress(
            stats,
            stage="done",
            message="Pipeline complete.",
            final=True,
        )

    _set_run_timestamps(enrich_finished_at=datetime.now(timezone.utc).isoformat())
    _persist_source_stats(
        scraped_by_source,
        removed_by_source,
        date_filtered_by_source,
        skipped_existing_by_source,
        kept_by_source,
        enriched_by_source,
        saved_by_source,
    )

    write_pipeline_stats(stats)


if __name__ == "__main__":
    main()
