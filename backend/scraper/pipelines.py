"""Streaming enrichment: a Scrapy item pipeline that cleans, analyzes,
embeds, and saves each article as soon as the spider yields it, instead of
buffering the whole crawl to a file and enriching it in a separate
subprocess afterward (see services/pipeline/pipeline.py, which used to run
`scrapy crawl -O raw_file` then `python -m services.articles.enrich` as two
sequential steps). This is what lets the dashboard show a source's results
while other sources are still being crawled, instead of waiting for the
slowest source in the run.

Reuses services/articles/enrich.py's exact per-article logic (clean, dedup,
date-window filter, analyze, embed, persist per-source stats) rather than
duplicating it - enrich.py itself stays as the batch/manual CLI entry point
(`scrapy crawl -O articles.json` then `python -m services.articles.enrich`,
still documented for offline/dev use), now sharing this file's logic instead
of diverging from it.

Only active for backend-triggered runs (PIPELINE_RUN_ID set - see
from_crawler below); a bare manual `scrapy crawl source_rss -O out.json` has
no run to stream progress into, so this pipeline is a no-op there and the
manual `enrich.py` step afterward is unaffected.

enrich_article()/get_embedding() are blocking network calls (LLM + embedding
model) - process_item() below hands each one to a dedicated worker thread
pool (config.ENRICH_CONCURRENCY workers, see its own comment for how that
number was chosen against DeepSeek/OpenAI/Ollama's actual limits) via
Twisted's deferToThreadPool, so N articles enrich concurrently instead of
one blocking the whole crawl's downloader at a time - the crawl itself and
other in-flight enrichments keep moving while any one LLM call is in
flight. The spider's own remaining blocking lookups (tweet hydration,
Google News link decoding, GDELT) are unaffected by this and still block
the reactor directly, same as before.
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
from threading import Lock

from scrapy.exceptions import NotConfigured
from twisted.internet.threads import deferToThreadPool
from twisted.python.threadpool import ThreadPool

import config
from analysis.aggregation import build_topic_insight
from embeddings import build_article_embedding_text, get_embedding
from services.articles import enrich
from services.articles.store import save_articles
from services.pipeline.pipeline_runs import update_pipeline_run


class StreamingEnrichPipeline:
    @classmethod
    def from_crawler(cls, crawler):
        if not enrich.PIPELINE_RUN_ID:
            # Manual/dev crawl (no backend-triggered run to stream progress
            # into) - stay out of the way entirely; enrich.py's file-based
            # CLI workflow still works unchanged.
            raise NotConfigured("StreamingEnrichPipeline only runs for backend-triggered pipeline runs.")
        return cls()

    def open_spider(self, spider):
        # Deferred import: grabbing the reactor before Scrapy has installed
        # its own chosen one (e.g. AsyncioSelectorReactor) can install the
        # wrong one first. By open_spider() the crawl has already started,
        # so Scrapy's reactor is definitely already installed.
        from twisted.internet import reactor

        self.reactor = reactor
        self.thread_pool = ThreadPool(minthreads=1, maxthreads=config.ENRICH_CONCURRENCY, name="enrich")
        self.thread_pool.start()

        # Guards every attribute below - process_item()'s slow section (the
        # actual LLM/embedding/DB calls) deliberately runs outside this lock
        # so those run concurrently across worker threads; only the shared
        # in-memory counters/seen_urls need protecting from concurrent
        # read-modify-write races.
        self.lock = Lock()
        self.project = enrich._load_project()
        self.project_context = enrich._load_project_context()
        self.seen_urls = set()
        self.scraped_by_source = Counter()
        self.removed_by_source = defaultdict(lambda: {"duplicate": 0, "blocked": 0})
        self.date_filtered_by_source = Counter()
        self.kept_by_source = Counter()
        self.enriched_by_source = Counter()
        self.saved_by_source = Counter()
        self.articles_cleaned_total = 0
        self.articles_saved_total = 0
        # Only for the end-of-run topic-insight log line (parity with
        # enrich.py's main()) - never persisted, see analysis/aggregation.py.
        self.enriched_articles = []

    def process_item(self, item, spider):
        return deferToThreadPool(self.reactor, self.thread_pool, self._process_item, dict(item))

    def _process_item(self, article):
        """Runs on a worker thread (see process_item) - up to
        config.ENRICH_CONCURRENCY of these run at once."""
        source = enrich._source_key(article)

        with self.lock:
            self.scraped_by_source[source] += 1
            cleaned, removed = enrich.clean_articles([article], seen_urls=self.seen_urls)
            for reason, count in (removed.get(source) or {}).items():
                self.removed_by_source[source][reason] += count
        if not cleaned:
            self._push_progress()
            return article
        article = cleaned[0]

        if self.project and not enrich._article_matches_project_window(article, self.project):
            with self.lock:
                self.date_filtered_by_source[source] += 1
            self._push_progress()
            return article

        with self.lock:
            self.kept_by_source[source] += 1
            self.articles_cleaned_total += 1

        # --- slow section: no lock held, runs concurrently across threads ---
        enrichment = enrich.enrich_article(article, project_context=self.project_context)
        if enrichment is None:
            enrichment = dict(enrich.DEFAULT_ENRICHMENT)
        if not enrichment.get("embedding_json"):
            embedding_text = build_article_embedding_text(article, enrichment)
            embedding = get_embedding(embedding_text)
            if embedding:
                enrichment.update(embedding)
        if not enrichment.get("analyzed_at"):
            enrichment["analyzed_at"] = datetime.now(timezone.utc).isoformat()
        enriched_article = {**article, **enrichment}
        saved_count, saved_delta = save_articles([enriched_article])
        # --- end slow section ---

        with self.lock:
            if enrichment.get("analysis_status") == "success":
                self.enriched_by_source[source] += 1
            self.enriched_articles.append(enriched_article)
            self.articles_saved_total += saved_count
            for saved_source, count in (saved_delta or {}).items():
                self.saved_by_source[saved_source] += count

        self._push_progress()
        return enriched_article

    def _push_progress(self):
        # Snapshot under the lock (cheap - copies of small dicts/Counters),
        # then push outside it so a slow DB round-trip from one thread never
        # blocks another thread's fast counter update. Threads can finish
        # out of order, so a push can occasionally write a smaller count
        # than one already written by a still-finishing article from
        # earlier - self-corrects on the very next push, not worth
        # sequencing more strictly for a live progress display.
        with self.lock:
            articles_cleaned_total = self.articles_cleaned_total
            articles_saved_total = self.articles_saved_total
            scraped_snapshot = Counter(self.scraped_by_source)
            removed_snapshot = {source: dict(counts) for source, counts in self.removed_by_source.items()}
            date_filtered_snapshot = Counter(self.date_filtered_by_source)
            kept_snapshot = Counter(self.kept_by_source)
            enriched_snapshot = Counter(self.enriched_by_source)
            saved_snapshot = Counter(self.saved_by_source)

        # articles_scraped/crawl_pages/message/stage are owned by the spider
        # itself (source_rss.py's own _push_progress) - this only ever
        # touches the columns it's responsible for, so the two don't
        # overwrite each other's fields on the same pipeline_runs row.
        update_pipeline_run(
            enrich.PIPELINE_RUN_ID,
            articles_cleaned=articles_cleaned_total,
            articles_saved=articles_saved_total,
        )
        enrich._persist_source_stats(
            scraped_snapshot,
            removed_snapshot,
            date_filtered_snapshot,
            kept_snapshot,
            enriched_snapshot,
            saved_snapshot,
        )

    def close_spider(self, spider):
        # Scrapy doesn't fire spider_closed (and this hook) until every
        # process_item() deferred has already resolved, so no in-flight
        # enrichment is running by this point - safe to stop the pool.
        self.thread_pool.stop()
        self._push_progress()
        if self.enriched_articles:
            project_name = (self.project or {}).get("name") or "general"
            topic_insight = build_topic_insight(self.enriched_articles, topic_name=project_name)
            spider.logger.info("Topic insight summary: %s", (topic_insight.get("summary") or "")[:120])
