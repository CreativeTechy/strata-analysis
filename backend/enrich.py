"""The ENRICHER stage: clean scraped articles, tag them with DeepSeek, and hand
them to the saver (store.save_articles). Reads articles.json, writes
enriched_articles.json, then upserts to Supabase.
"""

import json
import time
import requests

import config
from store import save_articles

DEEPSEEK_API_KEY = config.DEEPSEEK_API_KEY
INPUT_FILE = "articles.json"
OUTPUT_FILE = "enriched_articles.json"
MIN_TEXT_LENGTH = 200  # drop articles shorter than this

# Used when no DeepSeek key is available, so the pipeline still produces
# rows that satisfy the Supabase schema instead of crashing.
DEFAULT_ENRICHMENT = {
    "summary": "",
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


def enrich_article(article, api_key):
    title = article.get("title", "")
    text = article.get("text", "")[:2000]  # cap to save tokens

    prompt = f"""Analyze this car news article and return ONLY a JSON object, no explanation.
Title: {title}
Text: {text}
Return this exact JSON structure:
{{
    "summary": "2 sentence summary",
    "car_models": ["list", "of", "car", "models", "mentioned"],
    "brands": ["list", "of", "brands"],
    "sentiment": "positive|negative|neutral",
    "category": "review|event|recall|auction|race|tech|industry|other",
    "relevance_score": 1
}}"""

    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 400,
                "temperature": 0.1
            },
            timeout=30
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(raw)
    except Exception as e:
        print(f"  Enrichment error for '{title[:50]}': {e}")
        return None


def write_output(articles):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(articles)} articles to {OUTPUT_FILE}")


def main():
    print(f"Loading articles from {INPUT_FILE}...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_articles = json.load(f)

    articles = clean_articles(raw_articles)

    if not articles:
        print("No articles to process after cleaning.")
        write_output([])
        return

    if not DEEPSEEK_API_KEY:
        print("DEEPSEEK_API_KEY not set — skipping AI enrichment, using defaults.")

    enriched = []
    for idx, article in enumerate(articles):
        title = article.get("title", "")[:60]
        if DEEPSEEK_API_KEY:
            print(f"[{idx + 1}/{len(articles)}] Enriching: {title}")
            enrichment = enrich_article(article, DEEPSEEK_API_KEY)
            if enrichment is None:
                enrichment = dict(DEFAULT_ENRICHMENT)
            time.sleep(0.5)  # be polite to the API
        else:
            enrichment = dict(DEFAULT_ENRICHMENT)
        enriched.append({**article, **enrichment})

    print(f"\nEnriched {len(enriched)} articles successfully.")

    # Always persist fresh output so the caller (main.py / cron) uploads
    # the data we just scraped, not a stale committed snapshot.
    write_output(enriched)

    # Hand off to the saver (single Supabase upsert path).
    if enriched:
        print("Uploading to Supabase...")
        save_articles(enriched)
        print("Done.")


if __name__ == "__main__":
    main()
