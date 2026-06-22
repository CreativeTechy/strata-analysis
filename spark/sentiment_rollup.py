"""Strata sentiment rollup — the de-noising + aggregation layer over crawl_pages.

This is NOT the enricher (that tags one article at a time). This runs over the
WHOLE crawl_pages table at once and makes the mass trustworthy:

  1. dedup near-identical posts (MinHash/LSH) so 100 promo copies == ~1 signal
  2. score sentiment on the UNIQUE set (pluggable; lexicon default, swap in DeepSeek)
  3. roll up per brand with a sample-size floor + confidence
  4. write results back to Supabase `sentiment_rollup`

Runs in Spark LOCAL mode (no cluster). I/O is via the Supabase REST API with the
service key, so no Postgres password / JDBC driver is needed.

Env:
  SUPABASE_URL, SUPABASE_SERVICE_KEY   (required)
  DEDUP_THRESHOLD (default 0.45 Jaccard distance), MIN_SAMPLE (default 20)

Run:  python sentiment_rollup.py     (Spark spins up locally)
"""

import os
import json
import requests
from pyspark.sql import SparkSession, functions as F, types as T
from pyspark.ml.feature import Tokenizer, HashingTF, MinHashLSH

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
# service_role key required (writes bypass RLS); accept the legacy SUPABASE_KEY name.
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_KEY"]
DEDUP_THRESHOLD = float(os.environ.get("DEDUP_THRESHOLD", "0.45"))
MIN_SAMPLE = int(os.environ.get("MIN_SAMPLE", "20"))

HEADERS = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}

BRANDS = [
    "bmw", "mercedes", "audi", "toyota", "honda", "ford", "chevrolet", "nissan",
    "porsche", "ferrari", "lamborghini", "tesla", "volkswagen", "hyundai", "kia",
    "mazda", "subaru", "lexus", "jeep", "dodge", "ram", "gmc", "cadillac", "volvo",
    "jaguar", "land rover", "maserati", "bentley", "rolls-royce", "bugatti",
    "mclaren", "aston martin", "genesis", "mitsubishi", "mini", "fiat",
    "alfa romeo", "peugeot", "renault", "citroen", "suzuki", "chrysler",
    "lincoln", "acura", "infiniti", "buick", "rivian", "lucid", "polestar",
]
POS = {"best", "great", "love", "impressive", "win", "strong", "praise", "boost",
       "record", "beautiful", "fast", "powerful", "success", "gain", "excellent"}
NEG = {"recall", "crash", "lawsuit", "problem", "slow", "weak", "decline", "cut",
       "fail", "issue", "delay", "drop", "worst", "fraud", "tense", "loss", "ban"}


# --------------------------------------------------------------------------- #
# I/O (Supabase REST)
# --------------------------------------------------------------------------- #
def fetch_crawl_pages():
    rows, offset, page = [], 0, 1000
    while True:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/crawl_pages",
            headers={**HEADERS, "Range-Unit": "items", "Range": f"{offset}-{offset + page - 1}"},
            params={"select": "id,url,source,title,text"}, timeout=60,
        )
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows


def write_rollup(records):
    requests.post(
        f"{SUPABASE_URL}/rest/v1/sentiment_rollup?on_conflict=brand",
        headers={**HEADERS, "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates"},
        data=json.dumps(records), timeout=60,
    ).raise_for_status()


# --------------------------------------------------------------------------- #
# UDFs: sentiment + brand extraction (swap sentiment for DeepSeek/a model later)
# --------------------------------------------------------------------------- #
@F.udf(T.DoubleType())
def sentiment_score(text):
    if not text:
        return 0.0
    toks = text.lower().split()
    p = sum(t.strip(".,!?\"'") in POS for t in toks)
    n = sum(t.strip(".,!?\"'") in NEG for t in toks)
    if p + n == 0:
        return 0.0
    return float(p - n) / float(p + n)  # -1..1


@F.udf(T.ArrayType(T.StringType()))
def find_brands(text):
    if not text:
        return []
    low = text.lower()
    return [b for b in BRANDS if b in low]


def label_col(score):
    return (F.when(score > 0.15, "positive")
             .when(score < -0.15, "negative")
             .otherwise("neutral"))


# --------------------------------------------------------------------------- #
def main():
    spark = (SparkSession.builder.appName("StrataSentimentRollup")
             .master(os.environ.get("SPARK_MASTER", "local[*]"))
             .config("spark.sql.shuffle.partitions", "8")
             .getOrCreate())
    spark.sparkContext.setLogLevel("WARN")

    raw = fetch_crawl_pages()
    print(f"Loaded {len(raw)} crawl_pages rows")
    if not raw:
        print("Nothing to process."); spark.stop(); return

    df = spark.createDataFrame(raw).filter(F.length("text") > 80)

    # ---- 1. Dedup near-identical posts (the 100-promos fix) ----
    words = Tokenizer(inputCol="text", outputCol="tok").transform(df)
    feats = HashingTF(inputCol="tok", outputCol="features", numFeatures=1 << 18).transform(words)
    feats = feats.filter(F.size("tok") > 0)
    model = MinHashLSH(inputCol="features", outputCol="hashes", numHashTables=5).fit(feats)

    pairs = (model.approxSimilarityJoin(feats, feats, DEDUP_THRESHOLD, distCol="dist")
             .filter("datasetA.id < datasetB.id"))
    dup_ids = pairs.select(F.col("datasetB.id").alias("id")).distinct()
    unique = feats.join(dup_ids, "id", "left_anti").select("id", "source", "title", "text")

    total, kept = df.count(), unique.count()
    print(f"Dedup: {total} -> {kept} unique ({total - kept} near-duplicates collapsed)")

    # ---- 2. Sentiment on the UNIQUE set ----
    scored = (unique
              .withColumn("score", sentiment_score("text"))
              .withColumn("label", label_col(F.col("score")))
              .withColumn("brand", F.explode(find_brands("text"))))

    # ---- 3. Roll up per brand with a sample-size floor ----
    roll = (scored.groupBy("brand").agg(
                F.count("*").alias("mentions"),
                F.round(F.avg("score"), 3).alias("avg_sentiment"),
                F.sum((F.col("label") == "positive").cast("int")).alias("positive"),
                F.sum((F.col("label") == "negative").cast("int")).alias("negative"),
                F.sum((F.col("label") == "neutral").cast("int")).alias("neutral"))
            .filter(F.col("mentions") >= MIN_SAMPLE)
            .withColumn("confidence",
                        F.when(F.col("mentions") >= 100, "high")
                         .when(F.col("mentions") >= MIN_SAMPLE, "medium")
                         .otherwise("low"))
            .orderBy(F.desc("mentions")))

    roll.show(50, truncate=False)

    # ---- 4. Write back to Supabase ----
    records = [r.asDict() for r in roll.collect()]
    if records:
        write_rollup(records)
        print(f"Wrote {len(records)} brand rollups to sentiment_rollup")
    spark.stop()


if __name__ == "__main__":
    main()
