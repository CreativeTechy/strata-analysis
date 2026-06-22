"""Deep-crawl engine for "Spider Mode".

Fans out from a seed URL across a site (BFS), streaming each discovered page for
the live graph and counting articles/words for the downstream Spark work. The
point is BIG volume, not 500 rows.

Two interchangeable engines, same event shape:
  - crawl4ai (preferred)  — used automatically when the package is importable
    (needs Python <= 3.12; its deps have no 3.13/3.14 wheels yet).
  - native (fallback)     — pure requests + parsel + trafilatura, already in the
    stack, so Spider Mode runs anywhere with zero extra install.

Both yield:
  {"type":"start", "engine": "...", "seed": "..."}
  {"type":"node",  url, depth, parent, title, words, is_article, source}
  {"type":"done",  stats:{pages, articles, words, sources, depth, engine}}
"""

import asyncio
import importlib.util
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from parsel import Selector

MIN_ARTICLE_WORDS = 120  # below this, a page is a link/nav node, not an article
CONCURRENCY = 12
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 StrataSpider"
    )
}

# --- Bonus: harvest tweets EMBEDDED in crawled pages (journalists embed them in
# stories) and hydrate them via the no-auth FxTwitter/syndication proxy. No X
# login, no API key — it rides the crawl the spider already does. ---
HARVEST_TWEETS = os.environ.get("HARVEST_TWEETS", "1") == "1"
MAX_TWEETS = int(os.environ.get("MAX_TWEETS", "40"))
TWEET_RE = re.compile(r'(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)')


def harvest_tweet_ids(html):
    """Return [(handle, id), ...] for tweets embedded in a page's HTML."""
    if not html:
        return []
    return [(m.group(1), m.group(2)) for m in TWEET_RE.finditer(html)]


def hydrate_tweet(handle, tid):
    """Fetch a tweet's text via FxTwitter (no auth). Returns dict or None."""
    try:
        r = requests.get(
            f"https://api.fxtwitter.com/{handle}/status/{tid}",
            headers={"User-Agent": "StrataSpider/1.0"}, timeout=15,
        )
        if not r.ok:
            return None
        t = (r.json() or {}).get("tweet") or {}
        text = (t.get("text") or "").strip()
        if not text:
            return None
        author = (t.get("author") or {}).get("screen_name") or handle
        return {
            "url": t.get("url") or f"https://twitter.com/{handle}/status/{tid}",
            "text": text, "author": author,
        }
    except Exception:
        return None


async def emit_tweets(tweet_ids, seed):
    """Hydrate harvested tweet ids and yield them as node events (is_article)."""
    count = 0
    for tid, handle in tweet_ids.items():
        if count >= MAX_TWEETS:
            break
        data = await asyncio.to_thread(hydrate_tweet, handle, tid)
        if not data:
            continue
        count += 1
        yield {
            "type": "node", "url": data["url"], "depth": 1, "parent": seed,
            "title": f"@{data['author']}", "words": len(data["text"].split()),
            "is_article": True, "source": f"x.com/{data['author']}",
            "_text": data["text"],
        }


def _has_crawl4ai():
    return importlib.util.find_spec("crawl4ai") is not None


async def deep_crawl_stream(seed, max_depth=2, max_pages=300):
    engine = _crawl4ai_stream if _has_crawl4ai() else _native_stream
    async for ev in engine(seed, max_depth, max_pages):
        yield ev


# --------------------------------------------------------------------------- #
# Native engine (always available)
# --------------------------------------------------------------------------- #
def _fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text


async def _native_stream(seed, max_depth, max_pages):
    yield {"type": "start", "engine": "native", "seed": seed}

    domain = urlparse(seed).netloc
    seen = {seed}
    frontier = [(seed, 0, None)]
    pages = articles = words = 0
    sources = set()
    deepest = 0
    tweets = {}  # {tweet_id: handle} harvested from embeds
    loop = asyncio.get_event_loop()

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        while frontier and pages < max_pages:
            batch = frontier[:CONCURRENCY]
            frontier = frontier[CONCURRENCY:]
            futures = {item[0]: loop.run_in_executor(pool, _fetch, item[0]) for item in batch}

            for url, depth, parent in batch:
                if pages >= max_pages:
                    break
                try:
                    html = await futures[url]
                except Exception:
                    continue

                pages += 1
                deepest = max(deepest, depth)
                source = urlparse(url).netloc
                sources.add(source)

                if HARVEST_TWEETS:
                    for h, tid in harvest_tweet_ids(html):
                        tweets.setdefault(tid, h)

                extracted = trafilatura.extract(html) or ""
                wcount = len(extracted.split())
                is_article = wcount >= MIN_ARTICLE_WORDS
                if is_article:
                    articles += 1
                    words += wcount

                sel = Selector(text=html)
                title = (sel.css("title::text").get() or "").strip()

                yield {
                    "type": "node", "url": url, "depth": depth, "parent": parent,
                    "title": title[:140], "words": wcount,
                    "is_article": is_article, "source": source,
                    "_text": extracted if is_article else "",  # server-side only
                }

                if depth < max_depth and len(seen) < max_pages * 5:
                    for href in sel.css("a::attr(href)").getall():
                        link = urljoin(url, href.split("#")[0].strip())
                        if (link.startswith("http")
                                and urlparse(link).netloc == domain
                                and link not in seen):
                            seen.add(link)
                            frontier.append((link, depth + 1, url))

            await asyncio.sleep(0)  # let the SSE response flush

    # Hydrate embedded tweets (no-auth) and emit them as article nodes.
    tweets_emitted = 0
    async for ev in emit_tweets(tweets, seed):
        tweets_emitted += 1
        pages += 1
        articles += 1
        words += ev["words"]
        yield ev

    yield {"type": "done", "stats": {
        "pages": pages, "articles": articles, "words": words,
        "sources": len(sources), "depth": deepest, "engine": "native",
        "tweets": tweets_emitted,
    }}


# --------------------------------------------------------------------------- #
# crawl4ai engine (used when installed)
# --------------------------------------------------------------------------- #
def _markdown_text(result):
    md = getattr(result, "markdown", "") or ""
    if isinstance(md, str):
        return md
    return getattr(md, "raw_markdown", "") or getattr(md, "fit_markdown", "") or ""


async def _crawl4ai_stream(seed, max_depth, max_pages):
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, HTTPCrawlerConfig
    from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy
    from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
    from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy

    yield {"type": "start", "engine": "crawl4ai", "seed": seed}

    http_strategy = AsyncHTTPCrawlerStrategy(
        browser_config=HTTPCrawlerConfig(follow_redirects=True, verify_ssl=False)
    )
    config = CrawlerRunConfig(
        deep_crawl_strategy=BFSDeepCrawlStrategy(
            max_depth=max_depth, max_pages=max_pages, include_external=False),
        scraping_strategy=LXMLWebScrapingStrategy(),
        stream=True, verbose=False,
    )

    pages = articles = words = 0
    sources = set()
    deepest = 0
    tweets = {}  # {tweet_id: handle} harvested from embeds

    async with AsyncWebCrawler(crawler_strategy=http_strategy) as crawler:
        async for result in await crawler.arun(seed, config=config):
            meta = result.metadata or {}
            depth = int(meta.get("depth", 0) or 0)
            text = _markdown_text(result)
            wcount = len(text.split())
            is_article = bool(result.success) and wcount >= MIN_ARTICLE_WORDS
            source = urlparse(result.url).netloc

            pages += 1
            deepest = max(deepest, depth)
            if source:
                sources.add(source)
            if is_article:
                articles += 1
                words += wcount

            if HARVEST_TWEETS:
                for h, tid in harvest_tweet_ids(getattr(result, "html", "") or ""):
                    tweets.setdefault(tid, h)

            yield {
                "type": "node", "url": result.url, "depth": depth,
                "parent": meta.get("parent_url"), "title": (meta.get("title") or "")[:140],
                "words": wcount, "is_article": is_article, "source": source,
                "_text": text if is_article else "",  # server-side only
            }

    tweets_emitted = 0
    async for ev in emit_tweets(tweets, seed):
        tweets_emitted += 1
        pages += 1
        articles += 1
        words += ev["words"]
        yield ev

    yield {"type": "done", "stats": {
        "pages": pages, "articles": articles, "words": words,
        "sources": len(sources), "depth": deepest, "engine": "crawl4ai",
        "tweets": tweets_emitted,
    }}
