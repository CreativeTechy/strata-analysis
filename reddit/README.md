# Reddit source

Pulls car-subreddit posts + top comments into `crawl_pages`, so Spark dedups and
sentiments Reddit opinions alongside the spider's crawl. Each comment is its own
row (one opinion = one row).

## Why credentials (not a login)
Reddit blocks anonymous access from server/CI IPs (403). This uses **read-only
application-only OAuth** — a free `client_id` + `secret`, **no user account
password, no cookies**. It's the official, stable API.

### Get credentials (2 min)
1. https://www.reddit.com/prefs/apps → **create another app**.
2. Type: **script** (or **web app**). Name: anything. Redirect URI: `http://localhost`.
3. Note the **client_id** (under the app name) and **secret**.

### Add as GitHub repo secrets
`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` (plus the existing `SUPABASE_*`).

## Run
Hosted: `.github/workflows/reddit-source.yml` runs every 8h (and on dispatch).

Local:
```bash
cd reddit && pip install -r requirements.txt
export SUPABASE_URL=... SUPABASE_SERVICE_KEY=...
export REDDIT_CLIENT_ID=... REDDIT_CLIENT_SECRET=...
python reddit_source.py
```

## Tuning (env)
- `REDDIT_SUBREDDITS` — comma list (default: cars, Autos, BMW, Toyota, …)
- `MAX_POSTS_PER_SUB` (25), `MAX_COMMENTS_PER_POST` (8), `REDDIT_COMMENTS` (1)

Output lands in `crawl_pages` (source = `reddit/r/<sub>`), then the Spark rollup
treats it like any other volume.
