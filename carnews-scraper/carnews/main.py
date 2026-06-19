import os
import json
import subprocess
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from pydantic import BaseModel

app = FastAPI()

# Allow frontend to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase Setup - Use environment variables in Render, fallback to provided keys
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://nfmxwnuvbrozueedkwzo.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5mbXh3bnV2YnJvenVlZWRrd3pvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MTg3MjE4MywiZXhwIjoyMDk3NDQ4MTgzfQ.Dmnq-7UrC1XWr63LsxApQCjcvVWZixJj8hhIiT2K4B4")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print("Warning: Could not initialize Supabase client. Check credentials.", e)

def run_scraper_pipeline():
    try:
        print("1. Starting Scrapy...")
        # Run Scrapy and output to articles.json
        subprocess.run(["python", "-m", "scrapy", "crawl", "carnews_rss", "-O", "articles.json"], check=True)
        
        print("2. Running Enrichment pipeline...")
        subprocess.run(["python", "enrich.py"], check=True)
        
        print("3. Uploading to Supabase...")
        with open('enriched_articles.json', 'r') as f:
            data = json.load(f)
            
        for article in data:
            try:
                supabase.table('articles').upsert({
                    "url": article.get("url"),
                    "source": article.get("source"),
                    "feed": article.get("feed"),
                    "title": article.get("title"),
                    "author": article.get("author"),
                    "published": article.get("published"),
                    "text": article.get("text"),
                    "fetched_at": article.get("fetched_at"),
                    "summary": article.get("summary"),
                    "sentiment": article.get("sentiment"),
                    "relevance_score": article.get("relevance_score"),
                    "category": article.get("category"),
                    "brands": article.get("brands", []),
                    "car_models": article.get("car_models", [])
                }, on_conflict="url").execute()
            except Exception as e:
                print(f"Failed to upload {article.get('title')}: {e}")
                
        print("🎉 Pipeline complete!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Pipeline failed: {e}")

@app.get("/")
def health_check():
    return {"status": "healthy", "service": "Strata Scraper API"}

@app.post("/scrape")
def trigger_scrape(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_scraper_pipeline)
    return {"message": "Scraper pipeline has been triggered in the background. It will upload to Supabase when finished."}
