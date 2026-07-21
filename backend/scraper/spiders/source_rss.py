"""
Generic source spider: RSS discovery -> web/social page fetch -> trafilatura extraction.

Run from the backend/ directory:
    scrapy crawl source_rss -O <output-file>

Sources come from Supabase via config.load_source_records() (or the SOURCES env var
override), so adding/removing a publisher does not require code changes. The
spider never hand-writes CSS selectors per site -- trafilatura extracts
title/date/text generically, so one spider covers every publisher.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
import scrapy
import trafilatura
from trafilatura.feeds import find_feed_urls

from config import load_source_records
from content_guard import is_blocked_domain, is_consent_title
from pipeline_runs import update_pipeline_run

PIPELINE_RUN_ID = os.environ.get("PIPELINE_RUN_ID", "").strip()
TWEET_STATUS_RE = re.compile(r'(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)')


class SourceRssSpider(scrapy.Spider):
    name = "source_rss"

    custom_settings = {
        # Be polite; raise these later when you add proxies.
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "ROBOTSTXT_OBEY": True,
        # A real UA avoids some trivial blocks.
        "USER_AGENT": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "RETRY_TIMES": 2,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._progress_pages = 0
        self._progress_articles = 0
        self._progress_last_update = 0.0

    def _push_progress(self, force=False):
        if not PIPELINE_RUN_ID:
            return

        now = time.monotonic()
        if not force and self._progress_pages and (now - self._progress_last_update) < 2.0:
            return

        self._progress_last_update = now
        try:
            update_pipeline_run(
                PIPELINE_RUN_ID,
                status="running",
                stage="scrape",
                message="Scraping configured sources...",
                crawl_pages=self._progress_pages,
                articles_scraped=self._progress_articles,
            )
        except Exception as exc:
            self.logger.debug("Progress update failed: %s", exc)

    async def start(self):
        for record in load_source_records():
            if not record.get("enabled", True):
                continue
            url = (record.get("url") or "").strip()
            if not url:
                continue
            source_type = (record.get("source_type") or "rss").strip().lower()
            self.logger.info(
                "Seed %s (%s) -> %s",
                record.get("name") or url,
                source_type,
                url,
            )
            yield scrapy.Request(
                url,
                callback=self.parse_source,
                meta={
                    "source_url": url,
                    "source_type": source_type,
                    "source_name": record.get("name") or url,
                    "dont_obey_robotstxt": source_type in {"social", "username", "hashtag"},
                },
            )
        self._push_progress(force=True)

    def start_requests(self):
        # Scrapy 2.16 with AsyncCrawlerProcess prefers `start()`. Keep the old
        # hook as a compatibility fallback for older runners.
        yield from ()

    def parse_source(self, response):
        source_type = (response.meta.get("source_type") or "rss").strip().lower()
        content_type = (response.headers.get(b"Content-Type") or b"").decode("utf-8", "ignore").lower()
        self.logger.info(
            "Response %s [%s] from %s",
            response.url,
            source_type,
            content_type or "unknown content-type",
        )
        is_feed_like = (
            "xml" in content_type
            or response.xpath("local-name(/*)").get() in {"rss", "feed"}
            or response.xpath("//item").get()
            or response.xpath("//entry").get()
        )

        if is_feed_like:
            # Feed content is unambiguous regardless of the configured source_type -
            # e.g. a "keyword" source now points at a Google News RSS search feed
            # (see sources_store._derive_term_url), not a plain web page.
            yield from self.parse_feed(response)
            return

        if source_type == "rss":
            yield from self.parse_homepage(response)
            return

        if source_type in {"social", "username", "hashtag"}:
            yield from self.parse_social_page(response)
            return

        follow_links = source_type in {"web", "keyword"}
        yield from self.parse_page(response, follow_links=follow_links)

    def parse_feed(self, response):
        """Parse RSS/Atom XML and follow each article link."""
        self._progress_pages += 1
        self._push_progress()
        response.selector.remove_namespaces()
        # RSS uses <item><link>text</link>, Atom uses <entry><link href="">
        links = response.xpath("//item/link/text()").getall()
        links += response.xpath("//entry/link/@href").getall()

        self.logger.info("Feed %s -> %d article links", response.url, len(links))

        for url in links:
            url = url.strip()
            if url:
                yield response.follow(
                    url,
                    callback=self.parse_article,
                    meta={"source_url": response.url},
                )

    def parse_homepage(self, response):
        """Fallback for RSS homepage URLs that do not expose a feed directly."""
        self.logger.info("Homepage %s -> discovering feeds/articles", response.url)

        discovered_feeds = []
        try:
            discovered_feeds = find_feed_urls(response.url)
        except Exception:
            discovered_feeds = []

        if discovered_feeds:
            for feed_url in discovered_feeds:
                yield response.follow(feed_url, callback=self.parse_feed, meta={"source_url": feed_url})
            return

        yield from self.parse_page(response, follow_links=True)

    def parse_page(self, response, follow_links=False):
        """Extract a page directly, optionally following same-domain links."""
        self._progress_pages += 1
        self._push_progress()
        self.logger.info("Page %s -> extracting%s", response.url, " and following links" if follow_links else "")

        yield from self._yield_article(response)

        if not follow_links:
            return

        seen = set()
        max_links = 120
        article_links = []
        selectors = [
            'a[href*="/20"]::attr(href)',
            'article a::attr(href)',
            'h1 a::attr(href)',
            'h2 a::attr(href)',
            'h3 a::attr(href)',
            'main a::attr(href)',
            'a::attr(href)',
        ]
        for selector in selectors:
            article_links.extend(response.css(selector).getall())

        for href in article_links:
            if len(seen) >= max_links:
                break
            link = urljoin(response.url, href.split("#")[0].strip())
            if not link or link in seen:
                continue
            seen.add(link)
            if urlparse(link).netloc != urlparse(response.url).netloc:
                continue
            if "javascript:" in link.lower() or "mailto:" in link.lower() or "tel:" in link.lower():
                continue
            yield response.follow(
                link,
                callback=self.parse_article,
                meta={"source_url": response.url, "source_type": "web"},
            )

    def parse_social_page(self, response):
        """Best-effort extraction for X/Twitter sources."""
        self._progress_pages += 1
        self._push_progress()
        self.logger.info("Social page %s -> extracting", response.url)

        yield from self._yield_article(response)

        seen = set()
        for href in response.css('a[href*="/status/"]::attr(href)').getall():
            if len(seen) >= 40:
                break
            link = urljoin(response.url, href.split("#")[0].strip())
            if not link or link in seen:
                continue
            seen.add(link)
            if urlparse(link).netloc not in {"x.com", "twitter.com"}:
                continue
            yield response.follow(
                link,
                callback=self.parse_article,
                meta={"source_url": response.url, "source_type": "social", "dont_obey_robotstxt": True},
            )

    def _yield_article(self, response):
        if is_blocked_domain(response.url):
            # Google's own domains (search, consent, accounts, policy pages)
            # never host editorial content - skip before spending time on
            # trafilatura extraction.
            self.logger.info("Skipping Google domain (not an article): %s", response.url)
            return

        status_match = TWEET_STATUS_RE.search(response.url or "")
        if status_match:
            tweet = self._hydrate_tweet(response.url)
            if tweet:
                yield tweet
                self._progress_articles += 1
                self._push_progress()
                return

        extracted = trafilatura.extract(
            response.text,
            url=response.url,
            output_format="json",
            with_metadata=True,
            include_comments=False,
        )
        if not extracted:
            return

        doc = json.loads(extracted)
        text = (doc.get("text") or "").strip()
        title = doc.get("title") or ""
        if is_consent_title(title):
            # Defense in depth: a cookie/consent interstitial reached via
            # redirect (e.g. from a link that ends up on google.com) can carry
            # a non-Google response.url, so also check the extracted title.
            self.logger.info("Skipping consent/interstitial page (title match): %s", response.url)
            return
        if len(text) < 300:  # skip stubs/galleries/redirect shells
            return

        yield {
            "url": response.url,
            "source": urlparse(response.url).netloc,
            "source_url": response.meta.get("source_url"),
            "title": doc.get("title"),
            "author": doc.get("author"),
            "published": doc.get("date"),
            "text": text,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        self._progress_articles += 1
        self._push_progress()

    def parse_article(self, response):
        """Extract clean text + metadata with trafilatura (no per-site selectors)."""
        yield from self._yield_article(response)

    @staticmethod
    def _hydrate_tweet(url):
        match = TWEET_STATUS_RE.search(url or "")
        if not match:
            return None

        handle, tid = match.groups()
        try:
            resp = requests.get(
                f"https://api.fxtwitter.com/{handle}/status/{tid}",
                headers={"User-Agent": "StrataSpider/1.0"},
                timeout=15,
            )
            if not resp.ok:
                return None
            tweet = (resp.json() or {}).get("tweet") or {}
            text = (tweet.get("text") or "").strip()
            if not text:
                return None
            author = (tweet.get("author") or {}).get("screen_name") or handle
            return {
                "url": tweet.get("url") or f"https://twitter.com/{handle}/status/{tid}",
                "source": f"x.com/{author}",
                "source_url": url,
                "title": f"@{author}",
                "author": author,
                "published": tweet.get("created_at"),
                "text": text,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception:
            return None
