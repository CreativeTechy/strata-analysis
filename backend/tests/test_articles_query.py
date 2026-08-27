import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.articles import articles_query


class ListIdeaClustersForProjectTests(unittest.TestCase):
    def test_falsy_project_id_returns_empty_page_without_querying(self):
        with patch("services.articles.articles_query.db.fetch_all") as mock_fetch_all:
            result = articles_query.list_idea_clusters_for_project(None)
        self.assertEqual(result, {"clusters": [], "total": 0, "limit": 50, "offset": 0})
        mock_fetch_all.assert_not_called()

    def test_no_database_configured_returns_empty_page(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", ""):
            result = articles_query.list_idea_clusters_for_project(1)
        self.assertEqual(result["clusters"], [])
        self.assertEqual(result["total"], 0)

    def test_returns_rows_and_total_from_the_query(self):
        rows = [{"id": 1, "idea": "charging is slow", "frequency_estimate": 3}]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=rows) as mock_fetch_all:
                with patch("services.articles.articles_query.db.fetch_one", return_value={"total": 7}):
                    result = articles_query.list_idea_clusters_for_project(1, limit=10, offset=5)
        self.assertEqual(result, {"clusters": rows, "total": 7, "limit": 10, "offset": 5})
        args, _ = mock_fetch_all.call_args
        self.assertIn("idea_clusters", args[0])

    def test_query_error_returns_empty_page_instead_of_raising(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", side_effect=RuntimeError("boom")):
                result = articles_query.list_idea_clusters_for_project(1)
        self.assertEqual(result["clusters"], [])


class ListArticlesForIdeaClusterTests(unittest.TestCase):
    def test_no_database_configured_returns_none(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", ""):
            self.assertIsNone(articles_query.list_articles_for_idea_cluster(1, 2))

    def test_cluster_not_in_project_returns_none(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_one", return_value=None):
                self.assertIsNone(articles_query.list_articles_for_idea_cluster(1, 2))

    def test_returns_articles_page_when_cluster_belongs_to_project(self):
        article_rows = [{"id": 10, "title": "EV Review"}]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_one", side_effect=[{"id": 1}, {"total": 1}]):
                with patch("services.articles.articles_query.db.fetch_all", return_value=article_rows):
                    result = articles_query.list_articles_for_idea_cluster(1, 2)
        self.assertEqual(result, {"articles": article_rows, "total": 1, "limit": 10, "offset": 0})

    def test_query_error_returns_none(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_one", side_effect=RuntimeError("boom")):
                self.assertIsNone(articles_query.list_articles_for_idea_cluster(1, 2))


class GetAnalysisStatusCountsTests(unittest.TestCase):
    def test_no_database_configured_returns_empty(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", ""):
            self.assertEqual(articles_query.get_analysis_status_counts(), {})

    def test_scoped_to_project_joins_article_projects(self):
        rows = [{"analysis_status": "success", "total": 5}, {"analysis_status": "failed", "total": 2}]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=rows) as mock_fetch_all:
                result = articles_query.get_analysis_status_counts(project_id=1)
        self.assertEqual(result, {"success": 5, "failed": 2})
        args, _ = mock_fetch_all.call_args
        self.assertIn("article_projects", args[0])

    def test_unscoped_counts_all_articles(self):
        rows = [{"analysis_status": "success", "total": 10}]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=rows) as mock_fetch_all:
                result = articles_query.get_analysis_status_counts()
        self.assertEqual(result, {"success": 10})
        args, _ = mock_fetch_all.call_args
        self.assertNotIn("article_projects", args[0])

    def test_query_error_returns_empty_instead_of_raising(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", side_effect=RuntimeError("boom")):
                self.assertEqual(articles_query.get_analysis_status_counts(), {})


class ListAnalysisErrorsTests(unittest.TestCase):
    def test_no_database_configured_returns_empty_page(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", ""):
            result = articles_query.list_analysis_errors()
        self.assertEqual(result, {"errors": [], "total": 0, "limit": 24, "offset": 0})

    def test_filters_to_failed_status(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[]) as mock_fetch_all:
                with patch("services.articles.articles_query.db.fetch_one", return_value={"total": 0}):
                    articles_query.list_analysis_errors()
        args, _ = mock_fetch_all.call_args
        self.assertIn("analysis_status = 'failed'", args[0])

    def test_project_scoping_adds_article_projects_filter(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[]) as mock_fetch_all:
                with patch("services.articles.articles_query.db.fetch_one", return_value={"total": 0}):
                    articles_query.list_analysis_errors(project_id=3)
        sql, params = mock_fetch_all.call_args.args
        self.assertIn("article_projects", sql)
        self.assertIn(3, params)

    def test_query_error_returns_empty_page(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", side_effect=RuntimeError("boom")):
                result = articles_query.list_analysis_errors()
        self.assertEqual(result["errors"], [])


class GetArticleAnalysisTests(unittest.TestCase):
    def setUp(self):
        articles_query._live_articles_columns.cache_clear()

    def tearDown(self):
        articles_query._live_articles_columns.cache_clear()

    def test_no_database_configured_returns_none(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", ""):
            self.assertIsNone(articles_query.get_article_analysis(1))

    def test_article_not_found_returns_none(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[]):
                with patch("services.articles.articles_query.db.fetch_one", return_value=None):
                    self.assertIsNone(articles_query.get_article_analysis(999))

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
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[{"column_name": k} for k in row]):
                with patch("services.articles.articles_query.db.fetch_one", return_value=row):
                    result = articles_query.get_article_analysis(1)
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
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[]):
                with patch("services.articles.articles_query.db.fetch_one", return_value=row):
                    result = articles_query.get_article_analysis(1)
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
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[{"column_name": k} for k in row]):
                with patch("services.articles.articles_query.db.fetch_one", return_value=row):
                    result = articles_query.get_article_analysis(1)
        self.assertEqual(result["analysis_status"], "failed")
        self.assertEqual(result["analysis_error"], "model_unavailable")
        self.assertTrue(result["confidence"]["sentiment_low_confidence"])

    def test_query_error_returns_none(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[]):
                with patch("services.articles.articles_query.db.fetch_one", side_effect=RuntimeError("boom")):
                    self.assertIsNone(articles_query.get_article_analysis(1))


if __name__ == "__main__":
    unittest.main()
