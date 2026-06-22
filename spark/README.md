# Spark sentiment rollup

The de-noising + aggregation layer over `crawl_pages`. Not the enricher (which
tags one article at a time) — this runs over the whole table at once:

1. **Dedup** near-identical posts (MinHash/LSH) → 100 promo copies collapse to ~1.
2. **Sentiment** on the unique set (lexicon by default; swap in DeepSeek/a model).
3. **Roll up** per brand with a sample-size floor + confidence.
4. **Write** results to Supabase `sentiment_rollup`.

## No cluster required
Spark runs in **local mode** (`local[*]`) — one machine, all cores. Same code
scales to a cluster later by changing `SPARK_MASTER`; you only need a cluster
when the data outgrows one box (millions+ of rows).

## Setup
1. Create the output table: run `sentiment_rollup.sql` in Supabase.
2. Create the input table if you haven't: `../backend/crawl_pages.sql`.

## Run locally
```bash
cd spark
pip install -r requirements.txt          # needs Java 11+ on the machine
export SUPABASE_URL=https://YOUR.supabase.co
export SUPABASE_SERVICE_KEY=your-service-role-key
python sentiment_rollup.py
```

## Host on your current setup (free)
`.github/workflows/spark-rollup.yml` runs it on GitHub Actions every 6h (Java +
PySpark in local mode). Add repo secrets `SUPABASE_URL` + `SUPABASE_SERVICE_KEY`.
GH runners have ~7GB RAM — fine for hundreds of thousands of rows. Move to a real
cluster (Databricks / EMR / Dataproc / a VM) only when you outgrow that.

## Tuning
- `DEDUP_THRESHOLD` (Jaccard distance, default 0.45) — lower = stricter dedup.
- `MIN_SAMPLE` (default 20) — min unique mentions before a brand is reported.

## Swapping in real sentiment
Replace the `sentiment_score` UDF with a call to DeepSeek (batch the unique rows)
or a local transformer model. Everything else — dedup, rollup, write — stays.
