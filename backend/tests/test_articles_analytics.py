import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.articles import articles_analytics


class FetchRowsForStatsPagingTests(unittest.TestCase):
    """Distinct from articles_query.MAX_LIMIT (a single API page) and
    articles_search.SEARCH_SCAN_LIMIT (one search's in-memory scan) - this is
    the stats rollup's own bulk reader, capped at whatever `limit` the caller
    passes (get_article_stats always passes its own default)."""

    def _fake_db(self, total, columns=("id", "url", "title")):
        rows_all = [{column: f"{column}-{i}" for column in columns} for i in range(total)]

        def fetch_all(sql, params=()):
            limit, offset = params[-2], params[-1]
            return rows_all[offset:offset + limit]

        return fetch_all

    def _run(self, total, call):
        patchers = [
            patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"),
            patch("services.articles.articles_query.db.fetch_all", side_effect=self._fake_db(total)),
            patch("services.articles.articles_query.db.fetch_one", return_value={"total": total}),
        ]
        for patcher in patchers:
            patcher.start()
        try:
            return call()
        finally:
            for patcher in patchers:
                patcher.stop()

    def test_stats_read_every_article_up_to_its_cap(self):
        rows = self._run(900, lambda: articles_analytics._fetch_rows_for_stats(limit=1000))
        self.assertEqual(len(rows), 900)

    def test_stats_still_honour_their_total_cap(self):
        rows = self._run(2500, lambda: articles_analytics._fetch_rows_for_stats(limit=1000))
        self.assertEqual(len(rows), 1000)


class ComputeOverallToneTests(unittest.TestCase):
    def test_matching_tones_pass_through(self):
        self.assertEqual(articles_analytics.compute_overall_tone("critical", "critical"), "critical")

    def test_one_neutral_defers_to_the_other(self):
        self.assertEqual(articles_analytics.compute_overall_tone("neutral", "enthusiastic"), "enthusiastic")

    def test_conflicting_non_neutral_tones_are_mixed(self):
        self.assertEqual(articles_analytics.compute_overall_tone("critical", "enthusiastic"), "mixed")


class GetArticleStatsTests(unittest.TestCase):
    """End-to-end smoke test: get_article_stats composes _count_articles (via
    articles_query, or articles_search when a search term is present) with
    _topic_summary's rollup - this pins that composition without a real DB."""

    def test_rolls_up_sentiment_counts_and_insights_without_a_search_term(self):
        rows = [
            {"id": 1, "sentiment": "positive", "article_category": "review", "insight_json": {"topic": "EVs"}},
            {"id": 2, "sentiment": "negative", "article_category": "review", "insight_json": {}},
        ]
        counts_by_sentiment = {None: 2, "positive": 1, "negative": 1, "neutral": 0, "mixed": 0}

        def fake_fetch_articles(*, sentiment=None, **kwargs):
            return [], counts_by_sentiment[sentiment]

        with patch("services.articles.articles_analytics._fetch_articles", side_effect=fake_fetch_articles), \
             patch("services.articles.articles_analytics._fetch_rows_for_stats", return_value=rows):
            result = articles_analytics.get_article_stats()
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["positive"], 1)
        self.assertEqual(result["negative"], 1)
        self.assertEqual(result["insights"]["topic"], "EVs")

    def test_routes_through_search_when_a_search_term_is_present(self):
        rows = [{"id": 1, "sentiment": "positive", "article_category": "review", "insight_json": {}}]
        with patch("services.articles.articles_analytics.search_results", return_value=(rows, 1)) as mock_search:
            result = articles_analytics.get_article_stats(search="battery")
        self.assertEqual(result["total"], 1)
        mock_search.assert_called()


if __name__ == "__main__":
    unittest.main()
