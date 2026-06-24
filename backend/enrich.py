"""The ENRICHER stage: clean scraped articles, tag them with DeepSeek, and hand
them to the saver (store.save_articles). Reads articles.json, writes
enriched_articles.json, then upserts to Supabase.
"""

import json
import os
import time
from pathlib import Path

import requests

import config
from pipeline_runs import update_pipeline_run
from store import save_articles

DEEPSEEK_API_KEY = config.DEEPSEEK_API_KEY
MIN_TEXT_LENGTH = 200
VALID_SENTIMENTS = {"positive", "negative", "neutral"}
VALID_CATEGORIES = {
    "review",
    "event",
    "recall",
    "auction",
    "race",
    "tech",
    "industry",
    "other",
}
STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage"
PIPELINE_RUN_ID = os.environ.get("PIPELINE_RUN_ID", "").strip()
INPUT_FILE = Path(os.environ.get("PIPELINE_RAW_FILE", "articles.json"))
OUTPUT_FILE = Path(os.environ.get("PIPELINE_ENRICHED_FILE", "enriched_articles.json"))
PIPELINE_STATS_FILE = Path(os.environ.get("PIPELINE_STATS_FILE", "")) if os.environ.get("PIPELINE_STATS_FILE") else None

# Used when no DeepSeek key is available, so the pipeline still produces
# rows that satisfy the Supabase schema instead of crashing.
DEFAULT_ENRICHMENT = {
    "summary": "",
    "entities": [],
    "organizations": [],
    "topics": [],
    "key_points": [],
    "risks": [],
    "opportunities": [],
    "car_models": [],
    "brands": [],
    "sentiment": "neutral",
    "category": "other",
    "relevance_score": 0,
}


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
            "Analyze this article and return ONLY a JSON object, no explanation.\n"
            "Title: {title}\n"
            "Text: {text}\n"
            "Return this exact JSON structure:\n"
            "{\n"
            '    "summary": "2 sentence summary",\n'
            '    "entities": ["people", "products", "projects", "places"],\n'
            '    "organizations": ["companies", "groups", "institutions"],\n'
            '    "topics": ["main", "themes"],\n'
            '    "key_points": ["short", "bullets"],\n'
            '    "risks": ["risks", "or", "concerns"],\n'
            '    "opportunities": ["opportunities", "or", "upsides"],\n'
            '    "sentiment": "positive|negative|neutral",\n'
            '    "category": "review|event|recall|auction|race|tech|industry|other",\n'
            '    "relevance_score": 1\n'
            "}"
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


def _normalize_relevance_score(value):
    try:
        score = float(value)
    except Exception:
        return 0
    return max(0, min(score, 10))


def _validate_enrichment(payload):
    if not isinstance(payload, dict):
        return None

    summary = str(payload.get("summary", "")).strip()
    if not summary:
        return None

    sentiment = str(payload.get("sentiment", "neutral")).strip().lower()
    if sentiment not in VALID_SENTIMENTS:
        sentiment = "neutral"

    category = str(payload.get("category", "other")).strip().lower()
    if category not in VALID_CATEGORIES:
        category = "other"

    organizations = _as_list(payload.get("organizations") or payload.get("brands"))
    entities = _as_list(payload.get("entities") or payload.get("car_models"))
    topics = _as_list(payload.get("topics"))
    key_points = _as_list(payload.get("key_points"))
    risks = _as_list(payload.get("risks"))
    opportunities = _as_list(payload.get("opportunities"))

    return {
        "summary": summary,
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
    }


def enrich_article(article, api_key):
    title = article.get("title", "")
    text = article.get("text", "")[:2000]
    prompt = (
        _load_prompt_template()
        .replace("{title}", title)
        .replace("{text}", text)
    )

    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 400,
                "temperature": 0.1,
            },
            timeout=30,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(_strip_code_fences(raw))
        validated = _validate_enrichment(parsed)
        if validated is None:
            raise ValueError("DeepSeek returned JSON that did not match the enrichment schema")
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
        return

    if not DEEPSEEK_API_KEY:
        print("DEEPSEEK_API_KEY not set - skipping AI enrichment, using defaults.")

    enriched = []
    for idx, article in enumerate(articles):
        title = article.get("title", "")[:60]
        if DEEPSEEK_API_KEY:
            print(f"[{idx + 1}/{len(articles)}] Enriching: {title}")
            enrichment = enrich_article(article, DEEPSEEK_API_KEY)
            if enrichment is None:
                enrichment = dict(DEFAULT_ENRICHMENT)
            time.sleep(0.5)
        else:
            enrichment = dict(DEFAULT_ENRICHMENT)
        enriched.append({**article, **enrichment})

    stats["articles_enriched"] = len(enriched)
    print(f"\nEnriched {len(enriched)} articles successfully.")

    push_run_progress(
        stats,
        stage="enrich",
        message="Enrichment complete. Saving articles...",
    )

    write_output(enriched)

    if enriched:
        print("Uploading to Supabase...")
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
