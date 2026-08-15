import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.articles import articles_store


class ListIdeaClustersForProjectTests(unittest.TestCase):
    def test_falsy_project_id_returns_empty_page_without_querying(self):
        with patch("services.articles.articles_store.db.fetch_all") as mock_fetch_all:
            result = articles_store.list_idea_clusters_for_project(None)
        self.assertEqual(result, {"clusters": [], "total": 0, "limit": 50, "offset": 0})
        mock_fetch_all.assert_not_called()

    def test_no_database_configured_returns_empty_page(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", ""):
            result = articles_store.list_idea_clusters_for_project(1)
        self.assertEqual(result["clusters"], [])
        self.assertEqual(result["total"], 0)

    def test_returns_rows_and_total_from_the_query(self):
        rows = [{"id": 1, "idea": "charging is slow", "frequency_estimate": 3}]
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", return_value=rows) as mock_fetch_all:
                with patch("services.articles.articles_store.db.fetch_one", return_value={"total": 7}):
                    result = articles_store.list_idea_clusters_for_project(1, limit=10, offset=5)
        self.assertEqual(result, {"clusters": rows, "total": 7, "limit": 10, "offset": 5})
        args, _ = mock_fetch_all.call_args
        self.assertIn("idea_clusters", args[0])

    def test_query_error_returns_empty_page_instead_of_raising(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", side_effect=RuntimeError("boom")):
                result = articles_store.list_idea_clusters_for_project(1)
        self.assertEqual(result["clusters"], [])


class ListArticlesForIdeaClusterTests(unittest.TestCase):
    def test_no_database_configured_returns_none(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", ""):
            self.assertIsNone(articles_store.list_articles_for_idea_cluster(1, 2))

    def test_cluster_not_in_project_returns_none(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_one", return_value=None):
                self.assertIsNone(articles_store.list_articles_for_idea_cluster(1, 2))

    def test_returns_articles_page_when_cluster_belongs_to_project(self):
        article_rows = [{"id": 10, "title": "EV Review"}]
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_one", side_effect=[{"id": 1}, {"total": 1}]):
                with patch("services.articles.articles_store.db.fetch_all", return_value=article_rows):
                    result = articles_store.list_articles_for_idea_cluster(1, 2)
        self.assertEqual(result, {"articles": article_rows, "total": 1, "limit": 10, "offset": 0})

    def test_query_error_returns_none(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_one", side_effect=RuntimeError("boom")):
                self.assertIsNone(articles_store.list_articles_for_idea_cluster(1, 2))


class GetAnalysisStatusCountsTests(unittest.TestCase):
    def test_no_database_configured_returns_empty(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", ""):
            self.assertEqual(articles_store.get_analysis_status_counts(), {})

    def test_scoped_to_project_joins_article_projects(self):
        rows = [{"analysis_status": "success", "total": 5}, {"analysis_status": "failed", "total": 2}]
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", return_value=rows) as mock_fetch_all:
                result = articles_store.get_analysis_status_counts(project_id=1)
        self.assertEqual(result, {"success": 5, "failed": 2})
        args, _ = mock_fetch_all.call_args
        self.assertIn("article_projects", args[0])

    def test_unscoped_counts_all_articles(self):
        rows = [{"analysis_status": "success", "total": 10}]
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", return_value=rows) as mock_fetch_all:
                result = articles_store.get_analysis_status_counts()
        self.assertEqual(result, {"success": 10})
        args, _ = mock_fetch_all.call_args
        self.assertNotIn("article_projects", args[0])

    def test_query_error_returns_empty_instead_of_raising(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", side_effect=RuntimeError("boom")):
                self.assertEqual(articles_store.get_analysis_status_counts(), {})


class ListAnalysisErrorsTests(unittest.TestCase):
    def test_no_database_configured_returns_empty_page(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", ""):
            result = articles_store.list_analysis_errors()
        self.assertEqual(result, {"errors": [], "total": 0, "limit": 24, "offset": 0})

    def test_filters_to_failed_status(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", return_value=[]) as mock_fetch_all:
                with patch("services.articles.articles_store.db.fetch_one", return_value={"total": 0}):
                    articles_store.list_analysis_errors()
        args, _ = mock_fetch_all.call_args
        self.assertIn("analysis_status = 'failed'", args[0])

    def test_project_scoping_adds_article_projects_filter(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", return_value=[]) as mock_fetch_all:
                with patch("services.articles.articles_store.db.fetch_one", return_value={"total": 0}):
                    articles_store.list_analysis_errors(project_id=3)
        sql, params = mock_fetch_all.call_args.args
        self.assertIn("article_projects", sql)
        self.assertIn(3, params)

    def test_query_error_returns_empty_page(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", side_effect=RuntimeError("boom")):
                result = articles_store.list_analysis_errors()
        self.assertEqual(result["errors"], [])


class GetArticleAnalysisTests(unittest.TestCase):
    def setUp(self):
        articles_store._live_articles_columns.cache_clear()

    def tearDown(self):
        articles_store._live_articles_columns.cache_clear()

    def test_no_database_configured_returns_none(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", ""):
            self.assertIsNone(articles_store.get_article_analysis(1))

    def test_article_not_found_returns_none(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", return_value=[]):
                with patch("services.articles.articles_store.db.fetch_one", return_value=None):
                    self.assertIsNone(articles_store.get_article_analysis(999))

    def test_shapes_a_successful_analysis(self):
        row = {
            "id": 1, "url": "https://example.com/a", "title": "EV Review", "source": "example.com",
            "published": "2026-01-01", "sentiment": "positive", "article_category": "review",
            "writer_tone": "enthusiastic", "article_tone": "positive",
            "insight_json": {"summary": "Great car."}, "analyzed_at": "2026-01-01T00:00:00Z",
            "analysis_model": "sentiment=fake", "analysis_prompt_version": "analysis-pipeline/1",
            "analysis_status": "success", "analysis_error": None,
            "sentiment_score": 0.9, "sentiment_low_confidence": False,
            "sentiment_model": "fake-sentiment-model",
        }
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", return_value=[{"column_name": k} for k in row]):
                with patch("services.articles.articles_store.db.fetch_one", return_value=row):
                    result = articles_store.get_article_analysis(1)
        self.assertEqual(result["article_id"], 1)
        self.assertEqual(result["sentiment"], "positive")
        self.assertEqual(result["summary"], "Great car.")
        self.assertEqual(result["analysis_status"], "success")
        self.assertIsNone(result["analysis_error"])
        self.assertEqual(result["confidence"]["sentiment"], 0.9)
        self.assertFalse(result["confidence"]["sentiment_low_confidence"])
        self.assertEqual(result["models"]["sentiment"], "fake-sentiment-model")

    def test_malformed_insight_json_does_not_leak_through(self):
        row = {
            "id": 1, "url": "u", "title": "t", "source": "s", "published": None,
            "sentiment": "neutral", "article_category": "general_article",
            "writer_tone": "neutral", "article_tone": "neutral",
            "insight_json": "not a dict", "analyzed_at": None,
            "analysis_model": None, "analysis_prompt_version": None,
        }
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", return_value=[]):
                with patch("services.articles.articles_store.db.fetch_one", return_value=row):
                    result = articles_store.get_article_analysis(1)
        self.assertEqual(result["insight_json"], {})
        self.assertEqual(result["summary"], "")

    def test_failed_status_and_low_confidence_are_clearly_represented(self):
        row = {
            "id": 1, "url": "u", "title": "t", "source": "s", "published": None,
            "sentiment": "neutral", "article_category": "general_article",
            "writer_tone": "neutral", "article_tone": "neutral",
            "insight_json": {}, "analyzed_at": None, "analysis_model": None, "analysis_prompt_version": None,
            "analysis_status": "failed", "analysis_error": "model_unavailable",
            "sentiment_score": 0.2, "sentiment_low_confidence": True,
        }
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", return_value=[{"column_name": k} for k in row]):
                with patch("services.articles.articles_store.db.fetch_one", return_value=row):
                    result = articles_store.get_article_analysis(1)
        self.assertEqual(result["analysis_status"], "failed")
        self.assertEqual(result["analysis_error"], "model_unavailable")
        self.assertTrue(result["confidence"]["sentiment_low_confidence"])

    def test_query_error_returns_none(self):
        with patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_store.db.fetch_all", return_value=[]):
                with patch("services.articles.articles_store.db.fetch_one", side_effect=RuntimeError("boom")):
                    self.assertIsNone(articles_store.get_article_analysis(1))


class ContentHashTests(unittest.TestCase):
    """The fingerprint behind content_changed_at (migration 0017): it decides
    whether a re-scrape counts as the competitor having done something."""

    def test_reflowed_whitespace_is_not_a_change(self):
        """Markup re-wrapped between crawls must not read as news."""
        from services.articles import store

        self.assertEqual(
            store._content_hash("Cafe Younes opens a third roastery"),
            store._content_hash("Cafe   Younes\n\nopens a\tthird roastery\n"),
        )

    def test_a_real_edit_changes_the_hash(self):
        from services.articles import store

        self.assertNotEqual(
            store._content_hash("Espresso blend 250,000 LBP"),
            store._content_hash("Espresso blend 290,000 LBP"),
        )

    def test_empty_body_has_no_hash(self):
        """None rather than the hash of the empty string, so a page that failed
        to extract does not compare equal to every other failed extraction and
        freeze their change timestamps."""
        from services.articles import store

        self.assertIsNone(store._content_hash(""))
        self.assertIsNone(store._content_hash(None))
        self.assertIsNone(store._content_hash("   \n  "))


class BulkPagingTests(unittest.TestCase):
    """MAX_LIMIT caps what a single API response may return. Readers that walk
    the whole result set page through _fetch_articles, so if they ask for a
    page bigger than that cap they get a short page back and read it as "no
    more rows" - silently truncating at MAX_LIMIT. A 900-article project
    exported 100 articles because of exactly that."""

    def _fake_db(self, total, columns=("id", "url", "title")):
        rows_all = [{column: f"{column}-{i}" for column in columns} for i in range(total)]

        def fetch_all(sql, params=()):
            if "information_schema" in sql:
                # Let the export's column list fall back to ARTICLE_MUTABLE_FIELDS.
                return []
            limit, offset = params[-2], params[-1]
            return rows_all[offset:offset + limit]

        return fetch_all

    def _patched(self, total):
        return [
            patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"),
            patch("services.articles.articles_store.db.fetch_all", side_effect=self._fake_db(total)),
            patch("services.articles.articles_store.db.fetch_one", return_value={"total": total}),
        ]

    def _run(self, total, call):
        patchers = self._patched(total)
        for patcher in patchers:
            patcher.start()
        try:
            return call()
        finally:
            for patcher in patchers:
                patcher.stop()

    def test_export_returns_every_matching_article_not_just_the_first_page(self):
        rows = self._run(900, lambda: list(articles_store.export_articles()))
        self.assertEqual(len(rows), 900)

    def test_export_of_a_partial_page_still_terminates(self):
        rows = self._run(37, lambda: list(articles_store.export_articles()))
        self.assertEqual(len(rows), 37)

    def test_export_pages_are_contiguous_with_no_repeats_or_gaps(self):
        rows = self._run(900, lambda: list(articles_store.export_articles()))
        self.assertEqual([row["id"] for row in rows], [f"id-{i}" for i in range(900)])

    def test_export_streams_rather_than_building_the_whole_result_set(self):
        """The point of the generator: a caller that stops early must not have
        paid for every remaining page, and nothing may be read before the first
        row is asked for."""
        queries = []
        rows_all = [{"id": f"id-{i}", "url": f"url-{i}"} for i in range(2000)]

        def fetch_all(sql, params=()):
            if "information_schema" in sql:
                return []
            queries.append(params[-1])
            limit, offset = params[-2], params[-1]
            return rows_all[offset:offset + limit]

        patchers = [
            patch("services.articles.articles_store.config.DATABASE_URL", "postgresql://x"),
            patch("services.articles.articles_store.db.fetch_all", side_effect=fetch_all),
            patch("services.articles.articles_store.db.fetch_one", return_value={"total": 2000}),
        ]
        for patcher in patchers:
            patcher.start()
        try:
            stream = articles_store.export_articles()
            self.assertEqual(queries, [])  # nothing read until iteration starts

            first_page = [next(stream) for _ in range(articles_store.BULK_PAGE_SIZE)]
            self.assertEqual(len(first_page), articles_store.BULK_PAGE_SIZE)
            self.assertEqual(len(queries), 1)  # and only the first page was read

            stream.close()
        finally:
            for patcher in patchers:
                patcher.stop()

    def test_search_scan_reaches_its_own_limit_not_the_api_page_cap(self):
        rows = self._run(900, lambda: articles_store._fetch_all_articles(limit=articles_store.SEARCH_SCAN_LIMIT))
        self.assertEqual(len(rows), 900)

    def test_search_scan_still_stops_at_search_scan_limit(self):
        rows = self._run(2500, lambda: articles_store._fetch_all_articles(limit=articles_store.SEARCH_SCAN_LIMIT))
        self.assertEqual(len(rows), articles_store.SEARCH_SCAN_LIMIT)

    def test_stats_read_every_article_up_to_its_cap(self):
        rows = self._run(900, lambda: articles_store._fetch_rows_for_stats(limit=1000))
        self.assertEqual(len(rows), 900)

    def test_stats_still_honour_their_total_cap(self):
        rows = self._run(2500, lambda: articles_store._fetch_rows_for_stats(limit=1000))
        self.assertEqual(len(rows), 1000)

    def test_the_paginated_api_page_is_still_capped_at_max_limit(self):
        result = self._run(900, lambda: articles_store.list_articles(limit=5000))
        self.assertEqual(len(result["articles"]), articles_store.MAX_LIMIT)
        self.assertEqual(result["limit"], articles_store.MAX_LIMIT)


if __name__ == "__main__":
    unittest.main()
