"""
Car-news spider: RSS discovery -> article fetch -> trafilatura extraction.

Run from the backend/ directory:
    scrapy crawl carnews_rss -O <output-file>

Sources come from Supabase via config.load_feeds() (or the FEEDS env var
override), so adding/removing a publisher does not require code changes. The
spider never hand-writes CSS selectors per site -- trafilatura extracts
title/date/text generically, so one spider covers every publisher.
"""

import json
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import scrapy
import trafilatura
from trafilatura.feeds import find_feed_urls

from config import load_feeds


class CarNewsRssSpider(scrapy.Spider):
    name = "carnews_rss"

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

    start_urls = load_feeds()

    def parse(self, response):
        content_type = (response.headers.get(b"Content-Type") or b"").decode("utf-8", "ignore").lower()
        is_feed_like = (
            "xml" in content_type
            or response.xpath("local-name(/*)").get() in {"rss", "feed"}
            or response.xpath("//item").get()
            or response.xpath("//entry").get()
        )

        if is_feed_like:
            yield from self.parse_feed(response)
            return

        yield from self.parse_homepage(response)

    def parse_feed(self, response):
        """Parse RSS/Atom XML and follow each article link."""
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
                    meta={"feed": response.url},
                )

    def parse_homepage(self, response):
        """Fallback for homepage URLs that do not expose a feed directly."""
        self.logger.info("Homepage %s -> discovering feeds/articles", response.url)

        discovered_feeds = []
        try:
            discovered_feeds = find_feed_urls(response.url)
        except Exception:
            discovered_feeds = []

        if discovered_feeds:
            for feed_url in discovered_feeds:
                yield response.follow(feed_url, callback=self.parse_feed, meta={"feed": feed_url})
            return

        article_links = []
        selectors = [
            'a[href*="/20"]::attr(href)',
            'article a::attr(href)',
            'h2 a::attr(href)',
            'h3 a::attr(href)',
            'main a::attr(href)',
        ]
        for selector in selectors:
            article_links.extend(response.css(selector).getall())

        seen = set()
        for href in article_links:
            link = urljoin(response.url, href.split("#")[0].strip())
            if not link or link in seen:
                continue
            seen.add(link)
            if urlparse(link).netloc != urlparse(response.url).netloc:
                continue
            yield response.follow(
                link,
                callback=self.parse_article,
                meta={"feed": response.url},
            )

    def parse_article(self, response):
        """Extract clean text + metadata with trafilatura (no per-site selectors)."""
        extracted = trafilatura.extract(
            response.text,
            url=response.url,
            output_format="json",
            with_metadata=True,
            include_comments=False,
        )
        if not extracted:
            self.logger.debug("No extractable content: %s", response.url)
            return

        doc = json.loads(extracted)
        text = (doc.get("text") or "").strip()
        if len(text) < 300:  # skip stubs/galleries/redirect shells
            return

        yield {
            "url": response.url,
            "source": urlparse(response.url).netloc,
            "feed": response.meta.get("feed"),
            "title": doc.get("title"),
            "author": doc.get("author"),
            "published": doc.get("date"),
            "text": text,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
