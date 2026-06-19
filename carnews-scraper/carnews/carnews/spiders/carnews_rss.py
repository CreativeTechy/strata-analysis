r"""
Car-news spider: RSS discovery -> article fetch -> trafilatura extraction.

Drop this file into: D:\carnews-scraper\carnews\carnews\spiders\carnews_rss.py
Install the extractor first:  py -m pip install trafilatura

Run:
    py -m scrapy crawl carnews_rss -O articles.json

Add/remove feeds in the FEEDS list. The spider never hand-writes CSS
selectors per site -- trafilatura extracts title/date/text generically,
so one spider covers every publisher.
"""

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

import scrapy
import trafilatura

# Starter feed set -- swap in whatever publishers you care about.
FEEDS = [
    "https://www.motor1.com/rss/news/all/",
    "https://www.carscoops.com/feed/",
    "https://www.autoblog.com/rss.xml",
    "https://www.bmwblog.com/feed/",
]


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

    start_urls = FEEDS

    def parse(self, response):
        return self.parse_feed(response)

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
