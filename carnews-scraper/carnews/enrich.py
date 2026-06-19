import json
import csv
import time
import requests
from pathlib import Path

# --- CONFIG ---
DEEPSEEK_API_KEY = "sk-a9610af89f7a459bbe414f99d5b0e44a"
INPUT_FILE = "articles.json"
OUTPUT_JSON = "enriched_articles.json"
OUTPUT_CSV = "enriched_articles.csv"
MIN_TEXT_LENGTH = 200  # drop articles shorter than this

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
    print(f"✅ Cleaned: {len(articles)} → {len(cleaned)} articles")
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
  "relevance_score": 1-10
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
        content = response.json()["choices"][0]["message"]["content"]

        # strip markdown code fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        content = content.strip()

        enrichment = json.loads(content)
        return enrichment

    except Exception as e:
        print(f"  ⚠️ Failed: {e}")
        return {
            "summary": "",
            "car_models": [],
            "brands": [],
            "sentiment": "unknown",
            "category": "other",
            "relevance_score": 0
        }

def main():
    # load
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    # clean
    articles = clean_articles(articles)

    # enrich
    enriched = []
    for i, article in enumerate(articles):
        print(f"[{i+1}/{len(articles)}] {article.get('title', '')[:60]}...")
        enrichment = enrich_article(article, DEEPSEEK_API_KEY)
        merged = {**article, **enrichment}
        enriched.append(merged)
        time.sleep(0.5)  # be nice to the API

    # save JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Saved {OUTPUT_JSON}")

    # save CSV
    csv_fields = ["title", "url", "source", "author", "published",
                  "sentiment", "category", "relevance_score", "summary",
                  "car_models", "brands"]

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for a in enriched:
            row = dict(a)
            row["car_models"] = ", ".join(a.get("car_models", []))
            row["brands"] = ", ".join(a.get("brands", []))
            writer.writerow(row)
    print(f"✅ Saved {OUTPUT_CSV}")
    print(f"\n🎉 Done. {len(enriched)} articles enriched.")

if __name__ == "__main__":
    main()
