"""
Generic source spider: RSS discovery -> web/social page fetch -> trafilatura extraction.

Run from the backend/ directory:
    scrapy crawl source_rss -O <output-file>

Sources come from Supabase via config.load_source_records() (scoped to the
selected project's sources when PIPELINE_PROJECT_ID is set), so adding/removing
a publisher does not require code changes. The
spider never hand-writes CSS selectors per site -- trafilatura extracts
title/date/text generically, so one spider covers every publisher.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import scrapy
import trafilatura
from trafilatura.feeds import find_feed_urls

import config
from config import load_source_records
from content_guard import (
    is_blocked_domain,
    is_consent_title,
    is_telegram_channel_unavailable,
)
from scraper.social_sources import (
    extract_reddit_comment_tree,
    extract_reddit_listing,
    extract_telegram_messages,
    fetch_reddit_oauth_token,
    proxy_meta,
    reddit_fetch_url,
    reddit_oauth_comments_url,
    reddit_oauth_headers,
    reddit_oauth_request_url,
)
from services.pipeline.pipeline_runs import update_pipeline_run

PIPELINE_RUN_ID = os.environ.get("PIPELINE_RUN_ID", "").strip()
TWEET_STATUS_RE = re.compile(r'(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})/status/(\d+)')


def _parse_json_silent(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


# Response headers worth surfacing on a blocked fetch - which anti-bot/CDN
# vendor issued the block (Server/Via/CF-*), and any hint about how long to
# back off (Retry-After) - a bare status code alone doesn't say why.
_BLOCK_DETAIL_HEADERS = (
    b"Server", b"Via", b"CF-RAY", b"cf-mitigated", b"Retry-After",
    b"WWW-Authenticate", b"X-Robots-Tag", b"Content-Type", b"X-Cache",
)


def _describe_blocked_response(response):
    """Full diagnostic detail for a blocked (401/403/429) response: headers
    that identify the blocking vendor/reason plus a short body preview (an
    HTML challenge page reads very differently from a JSON API error, and
    that distinction is lost if only the status code is kept)."""
    headers = {}
    for name in _BLOCK_DETAIL_HEADERS:
        value = response.headers.get(name)
        if value is not None:
            headers[name.decode("ascii", "ignore")] = value.decode("utf-8", "ignore")
    try:
        body_preview = response.text[:300].strip().replace("\n", " ")
    except Exception:
        body_preview = ""
    parts = [f"HTTP {response.status} for {response.url}."]
    if headers:
        parts.append(f"Headers: {headers}.")
    if body_preview:
        parts.append(f"Body preview: {body_preview!r}")
    return " ".join(parts)


class SourceRssSpider(scrapy.Spider):
    name = "source_rss"

    custom_settings = {
        # Floor delay; AutoThrottle raises it per-domain based on observed
        # latency instead of hammering every site at the same fixed interval,
        # which is itself a bot signal to some anti-bot systems.
        "DOWNLOAD_DELAY": 0.5,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 1.0,
        "AUTOTHROTTLE_MAX_DELAY": 10.0,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "ROBOTSTXT_OBEY": True,
        # A real UA avoids some trivial blocks.
        "USER_AGENT": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        # A bare UA with no Accept/Accept-Language is itself a bot signal to
        # some anti-bot systems - fill in what a real browser sends.
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "RETRY_TIMES": 2,
    }

    # Reddit and (occasionally) Telegram return a flat 403/429 for requests
    # they've decided are automated traffic - most often anti-bot blocking of
    # datacenter/cloud IP ranges, not anything wrong with the request itself.
    # 401 is included for the Reddit-OAuth path (see start()) - an
    # expired/invalid token looks the same to the caller: nothing scraped,
    # no visible reason without this.
    BLOCKED_STATUS_CODES = (401, 403, 429)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._progress_pages = 0
        self._progress_articles = 0
        self._progress_last_update = 0.0
        # source_name -> {source_name, source_url, http_status, network_blocked, note}.
        # Pre-populated for every configured source in start() so a source
        # that never yields a single item (blocked, 404, DNS failure, ...)
        # still gets an entry - see closed()/_note_source_status() below and
        # services/pipeline/source_diagnostics.py, which merges this into the
        # per-source breakdown enrich.py already tracks by scraped-item count.
        self._source_reports = {}
        self._reddit_oauth_token = None

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

    def _note_source_status(self, source_name, source_url, http_status=None, blocked=False, note=None):
        """Record a fetch-time diagnostic for one configured source. Safe to
        call more than once per source (e.g. an errback then a later check) -
        later non-empty values simply overwrite earlier ones."""
        if not source_name:
            return
        report = self._source_reports.setdefault(
            source_name,
            {"source_name": source_name, "source_url": source_url, "http_status": None, "network_blocked": False, "note": None},
        )
        if http_status is not None:
            report["http_status"] = http_status
        if blocked:
            report["network_blocked"] = True
        if note:
            report["note"] = note

    def _on_request_error(self, failure):
        """errback for the initial per-source request (see start()) - catches
        connection-level failures (DNS, timeout, refused) that never produce
        an HTTP response at all, so parse_source's status check never runs."""
        request = failure.request
        source_name = request.meta.get("source_name")
        source_url = request.meta.get("source_url")
        message = str(getattr(failure, "value", "") or failure.getErrorMessage())
        self.logger.warning("Request failed for source %s: %s", source_name, message)
        print(f"[source_rss] REQUEST FAILED source={source_name!r} url={source_url!r} error={message}")
        self._note_source_status(source_name, source_url, note=f"Request failed: {message}")

    def closed(self, reason):
        """Scrapy calls this once when the spider finishes. Persist the
        per-source diagnostics to a side-channel file so enrich.py/pipeline.py
        can fold them into the pipeline run's data - the spider has no direct
        DB access of its own, only the run-level progress pushed via
        update_pipeline_run, which the next pipeline stage immediately
        overwrites once this subprocess exits."""
        if not self._source_reports:
            return
        workdir = os.environ.get("PIPELINE_WORKDIR", "").strip()
        if not workdir:
            return
        try:
            path = Path(workdir) / "source_diagnostics.json"
            path.write_text(json.dumps(list(self._source_reports.values()), indent=2), encoding="utf-8")
        except Exception as exc:
            self.logger.debug("Failed to write source_diagnostics.json: %s", exc)

    async def start(self):
        if config.reddit_oauth_configured():
            self._reddit_oauth_token = fetch_reddit_oauth_token()
            if self._reddit_oauth_token:
                self.logger.info("Reddit OAuth token acquired - reddit sources will use oauth.reddit.com.")
            else:
                self.logger.warning(
                    "REDDIT_OAUTH_CLIENT_ID/SECRET are set but the token request failed - "
                    "falling back to the public reddit.com .json endpoints for this run."
                )

        for record in load_source_records():
            if not record.get("enabled", True):
                continue
            url = (record.get("url") or "").strip()
            if not url:
                continue
            source_type = (record.get("source_type") or "rss").strip().lower()
            source_name = record.get("name") or url
            # Pre-populate before the request goes out, so a source that never
            # produces any response at all (see _on_request_error) still ends
            # up in source_diagnostics.json - not just ones that errored back.
            self._note_source_status(source_name, url)
            fetch_url = url
            if source_type == "reddit":
                fetch_url = (
                    (reddit_oauth_request_url(url) if self._reddit_oauth_token else reddit_fetch_url(url))
                    or url
                )
            self.logger.info(
                "Seed %s (%s) -> %s",
                source_name,
                source_type,
                fetch_url,
            )
            yield scrapy.Request(
                fetch_url,
                callback=self.parse_source,
                errback=self._on_request_error,
                headers=reddit_oauth_headers(self._reddit_oauth_token) if source_type == "reddit" else None,
                meta={
                    "source_url": url,
                    "source_type": source_type,
                    "source_name": source_name,
                    # "rss"/"keyword" sources are syndication feeds (or, for
                    # "keyword", a Google News RSS search feed - see
                    # sources_store._derive_term_url) the publisher already
                    # intends for aggregation, so robots.txt is skipped for
                    # them too. "web" sources crawl arbitrary same-domain
                    # pages beyond any feed (see parse_page's follow_links),
                    # which is exactly what robots.txt is meant to scope, so
                    # it stays honored there.
                    "dont_obey_robotstxt": source_type in {
                        "social", "username", "hashtag", "reddit", "telegram", "rss", "keyword",
                    },
                    # The telegram parser needs to see a raw redirect (private/
                    # missing channel) as its own status, not silently follow
                    # it into an unrelated app-install page - see
                    # content_guard.is_telegram_channel_unavailable.
                    "dont_redirect": source_type == "telegram",
                    # Without this, Scrapy's HttpErrorMiddleware silently drops
                    # any non-2xx/3xx response before parse_source ever sees
                    # it - every source type needs this now (not just
                    # reddit/telegram), so a plain 404/500 on the source's own
                    # page is visible too. See parse_source's status check.
                    "handle_httpstatus_all": True,
                    **proxy_meta(source_type),
                },
            )
        self._push_progress(force=True)

    def start_requests(self):
        # Scrapy 2.16 with AsyncCrawlerProcess prefers `start()`. Keep the old
        # hook as a compatibility fallback for older runners.
        yield from ()

    def parse_source(self, response):
        source_type = (response.meta.get("source_type") or "rss").strip().lower()
        source_name = response.meta.get("source_name")
        source_url = response.meta.get("source_url")

        # Root-request status gate, for every source type: this is the one
        # request per configured source that stands for "is this source
        # reachable at all" - downstream follow-up requests (individual
        # article links, reddit comment fetches, telegram discussion embeds)
        # deliberately do NOT feed into this, since one dead link among many
        # is normal web noise, not a sign the whole source is broken.
        if response.status in self.BLOCKED_STATUS_CODES:
            detail = _describe_blocked_response(response)
            self.logger.warning(
                "Source blocked (HTTP %s) - likely anti-bot protection against this server's "
                "network, not a problem with the source URL itself: %s",
                response.status,
                response.url,
            )
            # Explicit print (not just self.logger) so this is visible in
            # whatever captures this subprocess's stdout, regardless of the
            # scrapy LOG_LEVEL in effect - the whole point is to surface the
            # real cause (which vendor/why), not just "HTTP 403".
            print(f"[source_rss] BLOCKED source={source_name!r} {detail}")
            self._note_source_status(source_name, source_url, http_status=response.status, blocked=True, note=detail)
            return
        if source_type == "telegram" and is_telegram_channel_unavailable(response.status):
            self.logger.info(
                "Telegram channel unavailable (redirected - private, not a channel, or missing): %s",
                response.url,
            )
            self._note_source_status(
                source_name, source_url, http_status=response.status,
                note="Telegram channel unavailable (private, not a channel, or missing).",
            )
            return
        if response.status >= 400:
            detail = _describe_blocked_response(response)
            self.logger.warning("HTTP %s fetching source: %s", response.status, response.url)
            print(f"[source_rss] HTTP ERROR source={source_name!r} {detail}")
            self._note_source_status(source_name, source_url, http_status=response.status, note=detail)
            return

        content_type = (response.headers.get(b"Content-Type") or b"").decode("utf-8", "ignore").lower()
        self.logger.info(
            "Response %s [%s] from %s",
            response.url,
            source_type,
            content_type or "unknown content-type",
        )

        if source_type == "reddit":
            yield from self.parse_reddit_listing(response)
            return
        if source_type == "telegram":
            yield from self.parse_telegram_channel(response)
            return

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
                    # Propagate the configured source's own URL unchanged,
                    # not this feed page's URL - articles.source_url is
                    # matched exact-string against sources.url elsewhere
                    # (see services/intelligence/intelligence.py's
                    # keyword_existence_over_time source filter), so
                    # overwriting it here would silently break that filter
                    # for any source that goes through a homepage/feed hop.
                    meta={"source_url": response.meta.get("source_url"), "source_name": response.meta.get("source_name")},
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
                yield response.follow(
                    feed_url,
                    callback=self.parse_feed,
                    # See parse_feed's comment above - propagate the
                    # configured source's own URL, not the discovered feed's.
                    meta={"source_url": response.meta.get("source_url"), "source_name": response.meta.get("source_name")},
                )
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
                meta={
                    # See parse_feed's comment above - keep the configured
                    # source's own URL, not this page's URL.
                    "source_url": response.meta.get("source_url"),
                    "source_type": "web",
                    "source_name": response.meta.get("source_name"),
                },
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
                meta={
                    # See parse_feed's comment above - keep the configured
                    # source's own URL, not this page's URL.
                    "source_url": response.meta.get("source_url"),
                    "source_type": "social",
                    "source_name": response.meta.get("source_name"),
                    "dont_obey_robotstxt": True,
                },
            )

    def parse_reddit_listing(self, response):
        """Subreddit/user/search `.json` Listing -> post + comment items, plus
        a follow-up request per post for its full comment/reply tree."""
        self._progress_pages += 1
        self._push_progress()

        source_name = response.meta.get("source_name")
        source_url = response.meta.get("source_url")

        payload = _parse_json_silent(response.text)
        if payload is None:
            self.logger.info("Reddit listing was not valid JSON, skipping: %s", response.url)
            return

        items, permalinks = extract_reddit_listing(payload)
        if not items and not permalinks:
            self.logger.info("Reddit source unavailable or empty, skipping: %s", response.url)

        for item in items:
            yield self._reddit_article(item, source_name, source_url)

        for permalink in permalinks:
            comments_url = (
                (reddit_oauth_comments_url(permalink) if self._reddit_oauth_token else f"https://www.reddit.com{permalink}.json")
                or f"https://www.reddit.com{permalink}.json"
            )
            yield scrapy.Request(
                comments_url,
                callback=self.parse_reddit_comments,
                headers=reddit_oauth_headers(self._reddit_oauth_token),
                meta={
                    "source_url": source_url,
                    "source_name": source_name,
                    "dont_obey_robotstxt": True,
                    **proxy_meta("reddit"),
                },
            )

    def parse_reddit_comments(self, response):
        """A single post's `[post_listing, comments_listing]` detail JSON ->
        every comment and nested reply as its own item. A failed/blocked
        fetch here is a best-effort miss on one post's comments, not a
        source-level problem worth recording - see parse_source's status gate
        for what does count as source-level."""
        self._progress_pages += 1
        self._push_progress()

        source_name = response.meta.get("source_name")
        source_url = response.meta.get("source_url")

        payload = _parse_json_silent(response.text)
        if payload is None:
            self.logger.info("Reddit comments were not valid JSON, skipping: %s", response.url)
            return

        for item in extract_reddit_comment_tree(payload):
            yield self._reddit_article(item, source_name, source_url)

    def _reddit_article(self, item, source_name, source_url):
        self._progress_articles += 1
        self._push_progress()
        return {
            "url": item["url"],
            "source": f"reddit.com/r/{item['subreddit']}" if item["subreddit"] else "reddit.com",
            "source_url": source_url,
            "source_name": source_name,
            "title": item["title"],
            "author": item["author"],
            "published": item["published"],
            "text": item["text"],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    def parse_telegram_channel(self, response):
        """Public channel `t.me/s/<channel>` preview -> one item per message,
        plus a follow-up request per message for its discussion replies.
        Only ever called with a clean 2xx response - parse_source's status
        gate already handled blocked/unavailable/error responses."""
        self._progress_pages += 1
        self._push_progress()

        source_name = response.meta.get("source_name")
        source_url = response.meta.get("source_url")

        messages = extract_telegram_messages(response.selector)
        if not messages:
            self.logger.info("Telegram channel has no public messages: %s", response.url)
            return

        for message in messages:
            yield self._telegram_article(message, source_name, source_url)
            if message["channel"] and message["msg_id"]:
                yield scrapy.Request(
                    f"https://t.me/{message['channel']}/{message['msg_id']}?embed=1&discussion=1&comments_limit=50",
                    callback=self.parse_telegram_discussion,
                    meta={
                        "source_url": source_url,
                        "source_name": source_name,
                        "dont_obey_robotstxt": True,
                        "channel": message["channel"],
                        **proxy_meta("telegram"),
                    },
                )

    def parse_telegram_discussion(self, response):
        """Best-effort: a message's linked discussion-group replies, via the
        public comment-embed widget. Channels without a linked discussion
        group (the common case) return an empty widget with no messages -
        that is not an error, just nothing to yield. A failed/blocked fetch
        here is a miss on one message's replies, not a source-level problem -
        see parse_source's status gate for what does count as source-level."""
        self._progress_pages += 1
        self._push_progress()

        source_name = response.meta.get("source_name")
        source_url = response.meta.get("source_url")
        channel = response.meta.get("channel")

        for message in extract_telegram_messages(response.selector):
            yield self._telegram_article(message, source_name, source_url, channel=channel, is_reply=True)

    def _telegram_article(self, message, source_name, source_url, channel=None, is_reply=False):
        self._progress_articles += 1
        self._push_progress()
        channel = channel or message["channel"]
        if is_reply:
            title = f"Reply in @{channel} discussion" if channel else "Telegram discussion reply"
        else:
            title = f"Telegram post from @{channel}" if channel else "Telegram post"
        return {
            "url": message["url"],
            "source": f"t.me/{channel}" if channel else "t.me",
            "source_url": source_url,
            "source_name": source_name,
            "title": title,
            "author": message["author"],
            "published": message["published"],
            "text": message["text"],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    def _yield_article(self, response):
        if is_blocked_domain(response.url):
            # Google's own domains (search, consent, accounts, policy pages)
            # never host editorial content - skip before spending time on
            # trafilatura extraction.
            self.logger.info("Skipping Google domain (not an article): %s", response.url)
            return

        source_name = response.meta.get("source_name") or urlparse(response.url).netloc

        status_match = TWEET_STATUS_RE.search(response.url or "")
        if status_match:
            tweet = self._hydrate_tweet(response.url)
            if tweet:
                tweet["source_name"] = source_name
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
            "source_name": source_name,
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
