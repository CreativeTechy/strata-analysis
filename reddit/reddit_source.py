"""Reddit source -> crawl_pages.

Pulls posts (and their top comments) from car subreddits and upserts each as a
row in crawl_pages, so Spark dedups and sentiments Reddit opinions alongside the
spider's crawl. One comment = one independent opinion = one row = ideal unit.

Reddit blocks anonymous access from server/CI IPs, so this uses free, read-only
**application-only OAuth** (client_id + secret) — NOT a user login (no account
password/cookies). Register an app at https://www.reddit.com/prefs/apps
("script" or "web app"). If no creds are set, it falls back to the public .json
endpoints (only works from residential IPs).

Env:
  SUPABASE_URL, SUPABASE_SERVICE_KEY (or SUPABASE_KEY)   required
  REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET                 needed for server/CI
  REDDIT_SUBREDDITS    comma list (default below)
  MAX_POSTS_PER_SUB    default 25
  MAX_COMMENTS_PER_POST default 8
  REDDIT_COMMENTS      "1" to fetch comments (default "1")
"""

import os
import time
import json
import requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_KEY"]
CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")

SUBREDDITS = os.environ.get("REDDIT_SUBREDDITS", "").split(",") if os.environ.get("REDDIT_SUBREDDITS") else [
    "cars", "Autos", "whatcarshouldIbuy", "electricvehicles", "BMW", "Toyota",
    "Honda", "Ford", "teslamotors", "Cartalk", "askcarsales", "Porsche",
]
LISTINGS = ["hot", "top"]
MAX_POSTS_PER_SUB = int(os.environ.get("MAX_POSTS_PER_SUB", "25"))
MAX_COMMENTS_PER_POST = int(os.environ.get("MAX_COMMENTS_PER_POST", "8"))
FETCH_COMMENTS = os.environ.get("REDDIT_COMMENTS", "1") == "1"
MIN_CHARS = 25

UA = {"User-Agent": "StrataMedia/1.0 (car sentiment research)"}
REST = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}

# Acquire an app-only OAuth token if credentials are present.
TOKEN = None
if CLIENT_ID and CLIENT_SECRET:
    _r = requests.post("https://www.reddit.com/api/v1/access_token",
                       auth=(CLIENT_ID, CLIENT_SECRET),
                       data={"grant_type": "client_credentials"},
                       headers=UA, timeout=30)
    _r.raise_for_status()
    TOKEN = _r.json()["access_token"]
    print("Reddit: using application-only OAuth")
else:
    print("Reddit: no creds — falling back to public .json (residential IPs only)")

BASE = "https://oauth.reddit.com" if TOKEN else "https://www.reddit.com"


def reddit_get(path, params=None, tries=3):
    """GET a Reddit path (e.g. '/r/cars/hot' or a permalink). Handles OAuth vs
    public-json mode."""
    headers = dict(UA)
    if TOKEN:
        headers["Authorization"] = f"bearer {TOKEN}"
        url = BASE + path
    else:
        url = BASE + path + ".json"
    for attempt in range(tries):
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        time.sleep(1.0)  # be polite (60 req/min app-only limit)
        return r.json()
    return None


def listing_posts(sub, listing):
    params = {"limit": 100}
    if listing == "top":
        params["t"] = "week"
    data = reddit_get(f"/r/{sub}/{listing}", params)
    if not data:
        return []
    out = []
    for c in data.get("data", {}).get("children", []):
        d = c.get("data", {})
        if d.get("stickied"):
            continue
        out.append(d)
    return out


def post_comments(permalink):
    data = reddit_get(permalink.rstrip("/"), {"limit": 50, "depth": 1})
    if not data or len(data) < 2:
        return []
    bodies = []
    for c in data[1].get("data", {}).get("children", []):
        if c.get("kind") != "t1":
            continue
        d = c.get("data", {})
        body = (d.get("body") or "").strip()
        if len(body) >= MIN_CHARS and body not in ("[deleted]", "[removed]"):
            bodies.append((d.get("permalink", ""), body))
        if len(bodies) >= MAX_COMMENTS_PER_POST:
            break
    return bodies


def upsert(rows):
    if not rows:
        return 0
    sent = 0
    for i in range(0, len(rows), 50):
        batch = rows[i:i + 50]
        resp = requests.post(f"{SUPABASE_URL}/rest/v1/crawl_pages?on_conflict=url",
                             headers=REST, data=json.dumps(batch), timeout=30)
        if resp.ok:
            sent += len(batch)
        else:
            print(f"  upsert error {resp.status_code}: {resp.text[:120]}")
    return sent


def main():
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rows, seen = [], set()

    for sub in SUBREDDITS:
        sub = sub.strip()
        if not sub:
            continue
        posts = []
        for listing in LISTINGS:
            posts += listing_posts(sub, listing)
        # dedup posts within sub, cap
        uniq, ids = [], set()
        for p in posts:
            if p.get("id") and p["id"] not in ids:
                ids.add(p["id"]); uniq.append(p)
        uniq = uniq[:MAX_POSTS_PER_SUB]
        print(f"r/{sub}: {len(uniq)} posts")

        for p in uniq:
            permalink = p.get("permalink", "")
            url = "https://www.reddit.com" + permalink
            text = f"{p.get('title', '')}\n\n{p.get('selftext', '')}".strip()
            if url not in seen and len(text) >= MIN_CHARS:
                seen.add(url)
                rows.append({"crawl_id": f"reddit-{fetched_at[:10]}", "url": url,
                             "source": f"reddit/r/{sub}", "seed": f"r/{sub}",
                             "title": p.get("title", "")[:300], "text": text,
                             "words": len(text.split()), "depth": 0, "fetched_at": fetched_at})

            if FETCH_COMMENTS and p.get("num_comments", 0) > 0:
                for cperma, body in post_comments(permalink):
                    curl = "https://www.reddit.com" + cperma
                    if curl in seen:
                        continue
                    seen.add(curl)
                    rows.append({"crawl_id": f"reddit-{fetched_at[:10]}", "url": curl,
                                 "source": f"reddit/r/{sub}", "seed": f"r/{sub}",
                                 "title": p.get("title", "")[:300], "text": body,
                                 "words": len(body.split()), "depth": 1, "fetched_at": fetched_at})

    print(f"Collected {len(rows)} rows ({len(SUBREDDITS)} subreddits)")
    saved = upsert(rows)
    print(f"Upserted {saved} rows to crawl_pages")


if __name__ == "__main__":
    main()
