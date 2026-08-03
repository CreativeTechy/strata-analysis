"""Reddit + Telegram response parsing, kept free of Scrapy.

Split out of source_rss.py so this parsing logic is unit-testable without the
scrapy package installed (the spider module imports scrapy at load time,
which this module deliberately avoids) - only json-serializable dicts/lists
and, for Telegram, a parsel Selector (a much lighter transitive dependency
scrapy itself is built on) cross this boundary.
"""

from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

import config
from content_guard import is_reddit_blocked_payload

# --- Proxy support (optional) ---------------------------------------------


def proxy_meta(platform):
    """{"proxy": url} for reddit/telegram if REDDIT_PROXY_URL/TELEGRAM_PROXY_URL
    is set (see config.py), else {} - merge into a Scrapy request's meta dict
    with `**proxy_meta(platform)`. Scrapy's own HttpProxyMiddleware reads
    meta["proxy"], including any embedded user:pass basic-auth credentials."""
    proxy = {"reddit": config.REDDIT_PROXY_URL, "telegram": config.TELEGRAM_PROXY_URL}.get(platform, "")
    return {"proxy": proxy} if proxy else {}


# --- Reddit OAuth (optional) ------------------------------------------------
# App-only ("client_credentials") access via a registered Reddit app - see
# config.py's REDDIT_OAUTH_CLIENT_ID/_SECRET docstring for how to get one.
# Used instead of the public `.json` endpoints when configured; unconfigured
# (the default) leaves reddit_fetch_url()'s public-endpoint path untouched.

REDDIT_OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_OAUTH_API_BASE = "https://oauth.reddit.com"
_DEFAULT_OAUTH_USER_AGENT = "strata-media-scraper/1.0"


def fetch_reddit_oauth_token():
    """POST for an app-only OAuth token. Returns the bearer token string, or
    None if OAuth isn't configured or the request fails - callers must treat
    None as "fall back to the public `.json` endpoints", not as fatal."""
    if not config.reddit_oauth_configured():
        return None
    try:
        response = requests.post(
            REDDIT_OAUTH_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(config.REDDIT_OAUTH_CLIENT_ID, config.REDDIT_OAUTH_CLIENT_SECRET),
            headers={"User-Agent": config.REDDIT_OAUTH_USER_AGENT or _DEFAULT_OAUTH_USER_AGENT},
            timeout=15,
        )
        if not response.ok:
            return None
        return (response.json() or {}).get("access_token") or None
    except Exception:
        return None


def reddit_oauth_request_url(url):
    """Convert a stored reddit.com URL into the matching oauth.reddit.com API
    path. No `.json` suffix - the OAuth API returns JSON based on the
    Authorization header, not a URL suffix, unlike the public endpoints."""
    parsed = urlparse(url or "")
    path = (parsed.path or "").rstrip("/")
    if not path:
        return None
    if path.startswith("/search"):
        query = f"{parsed.query}&limit=25" if parsed.query else "limit=25"
        return f"{REDDIT_OAUTH_API_BASE}/search?{query}"
    return f"{REDDIT_OAUTH_API_BASE}{path}?limit=25"


def reddit_oauth_comments_url(permalink):
    return f"{REDDIT_OAUTH_API_BASE}{permalink}" if permalink else None


def reddit_oauth_headers(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


# --- Reddit -------------------------------------------------------------


def reddit_fetch_url(url):
    """Convert a stored reddit.com URL (subreddit/user/search) into the
    matching public `.json` listing endpoint - Reddit's most stable
    unauthenticated read endpoint, per stable public API access without login."""
    parsed = urlparse(url or "")
    path = (parsed.path or "").rstrip("/")
    if not path:
        return None
    base = "https://www.reddit.com/search.json" if path.startswith("/search") else f"https://www.reddit.com{path}.json"
    query = f"{parsed.query}&limit=25" if parsed.query else "limit=25"
    return f"{base}?{query}"


def _reddit_epoch_to_iso(value):
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _reddit_post_item(data):
    """Build an item dict for a Reddit post (`t3`), or None if unusable."""
    permalink = data.get("permalink")
    if not permalink:
        return None
    title = data.get("title") or ""
    text = (data.get("selftext") or "").strip() or title
    if not text:
        return None
    return {
        "url": f"https://www.reddit.com{permalink}",
        "subreddit": data.get("subreddit") or "",
        "title": title,
        "author": data.get("author"),
        "published": _reddit_epoch_to_iso(data.get("created_utc")),
        "text": text,
    }


def _reddit_comment_item(data, post_permalink=None):
    """Build an item dict for a Reddit comment/reply (`t1`), or None if
    unusable (deleted/removed body, or no way to build a stable URL)."""
    body = (data.get("body") or "").strip()
    if not body or body in {"[deleted]", "[removed]"}:
        return None
    comment_id = data.get("id") or ""
    permalink = data.get("permalink") or (f"{post_permalink}{comment_id}/" if post_permalink and comment_id else None)
    if not permalink:
        return None
    return {
        "url": f"https://www.reddit.com{permalink}",
        "subreddit": data.get("subreddit") or "",
        "title": data.get("link_title") or f"Comment by u/{data.get('author') or 'unknown'}",
        "author": data.get("author"),
        "published": _reddit_epoch_to_iso(data.get("created_utc")),
        "text": body,
    }


def extract_reddit_listing(payload):
    """From a subreddit/user/search Listing payload, return
    (post_and_comment_items, permalinks_to_fetch_full_comments_for)."""
    items = []
    permalinks = []
    if not isinstance(payload, dict) or is_reddit_blocked_payload(payload):
        return items, permalinks
    for child in (payload.get("data") or {}).get("children") or []:
        kind, data = child.get("kind"), child.get("data") or {}
        if kind == "t3":
            item = _reddit_post_item(data)
            if item:
                items.append(item)
            permalink = data.get("permalink")
            if permalink:
                permalinks.append(permalink)
        elif kind == "t1":
            item = _reddit_comment_item(data)
            if item:
                items.append(item)
    return items, permalinks


def extract_reddit_comment_tree(payload):
    """From a post-detail payload (`[post_listing, comments_listing]`),
    return every comment and nested reply as an item dict."""
    if not isinstance(payload, list) or len(payload) < 2:
        return []

    post_children = ((payload[0] or {}).get("data") or {}).get("children") or []
    post_permalink = (post_children[0].get("data") or {}).get("permalink") if post_children else None

    comments_listing = payload[1] or {}
    if is_reddit_blocked_payload(comments_listing):
        return []

    items = []

    def walk(node):
        kind, data = node.get("kind"), node.get("data") or {}
        if kind != "t1":
            return
        item = _reddit_comment_item(data, post_permalink)
        if item:
            items.append(item)
        replies = data.get("replies")
        if isinstance(replies, dict):
            for child in (replies.get("data") or {}).get("children") or []:
                walk(child)

    for child in (comments_listing.get("data") or {}).get("children") or []:
        walk(child)
    return items


# --- Telegram -------------------------------------------------------------
# extract_telegram_messages() takes a parsel Selector (or raw HTML text)
# rather than a Scrapy Response so it is reusable for both the channel page
# and the discussion-embed page - a Scrapy Response's `.selector` IS a parsel
# Selector, so the spider passes that straight through with no conversion.


def extract_telegram_messages(selector_or_html):
    from parsel import Selector

    selector = Selector(text=selector_or_html) if isinstance(selector_or_html, str) else selector_or_html

    items = []
    for wrap in selector.css(".tgme_widget_message_wrap"):
        message = wrap.css(".tgme_widget_message")
        data_post = message.attrib.get("data-post") if message else None
        if not data_post:
            continue
        text = " ".join(part.strip() for part in wrap.css(".tgme_widget_message_text ::text").getall() if part.strip())
        if not text:
            continue
        channel, _, msg_id = data_post.partition("/")
        published = wrap.css(".tgme_widget_message_date time::attr(datetime)").get()
        author = (wrap.css(".tgme_widget_message_owner_name, .tgme_widget_message_author").xpath("string()").get() or "").strip()
        items.append({
            "url": f"https://t.me/{data_post}",
            "channel": channel,
            "msg_id": msg_id,
            "text": text,
            "published": published,
            "author": author or channel,
        })
    return items
