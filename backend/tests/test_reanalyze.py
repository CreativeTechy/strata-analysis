import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.articles import reanalyze


class PrimaryProjectIdForArticleTests(unittest.TestCase):
    def test_exactly_one_linked_project_is_returned(self):
        with patch("services.articles.reanalyze.db.fetch_all", return_value=[{"project_id": 7}]):
            self.assertEqual(reanalyze._primary_project_id_for_article(1), 7)

    def test_zero_linked_projects_returns_none(self):
        with patch("services.articles.reanalyze.db.fetch_all", return_value=[]):
            self.assertIsNone(reanalyze._primary_project_id_for_article(1))

    def test_multiple_linked_projects_returns_none(self):
        with patch("services.articles.reanalyze.db.fetch_all", return_value=[{"project_id": 7}, {"project_id": 8}]):
            self.assertIsNone(reanalyze._primary_project_id_for_article(1))

    def test_query_error_returns_none(self):
        with patch("services.articles.reanalyze.db.fetch_all", side_effect=RuntimeError("boom")):
            self.assertIsNone(reanalyze._primary_project_id_for_article(1))


class ReanalyzeArticleTests(unittest.TestCase):
    ARTICLE_ROW = {"id": 1, "url": "https://example.com/a", "title": "t", "text": "x" * 300}

    def test_article_not_found_reports_not_found_without_running_analysis(self):
        with patch("services.articles.reanalyze.load_article_for_reanalysis", return_value=None), \
             patch("services.articles.reanalyze.analyze_article") as mock_analyze:
            result = reanalyze.reanalyze_article(999)
        self.assertFalse(result["ok"])
        self.assertEqual(result["analysis_status"], "not_found")
        mock_analyze.assert_not_called()

    def test_successful_analysis_saves_and_reports_ok(self):
        analysis_result = {"analysis_status": "success", "analysis_error": None, "sentiment": "positive"}
        with patch("services.articles.reanalyze.load_article_for_reanalysis", return_value=dict(self.ARTICLE_ROW)), \
             patch("services.articles.reanalyze._primary_project_id_for_article", return_value=5), \
             patch("services.articles.reanalyze.analyze_article", return_value=analysis_result), \
             patch("services.articles.reanalyze.save_articles", return_value=(1, {})) as mock_save:
            result = reanalyze.reanalyze_article(1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["analysis_status"], "success")
        args, kwargs = mock_save.call_args
        saved_articles = args[0]
        self.assertEqual(saved_articles[0]["url"], "https://example.com/a")
        self.assertEqual(saved_articles[0]["sentiment"], "positive")
        self.assertEqual(kwargs["project_id"], 5)

    def test_failed_analysis_status_is_not_ok_even_though_save_succeeded(self):
        analysis_result = {"analysis_status": "failed", "analysis_error": "model_unavailable"}
        with patch("services.articles.reanalyze.load_article_for_reanalysis", return_value=dict(self.ARTICLE_ROW)), \
             patch("services.articles.reanalyze._primary_project_id_for_article", return_value=None), \
             patch("services.articles.reanalyze.analyze_article", return_value=analysis_result), \
             patch("services.articles.reanalyze.save_articles", return_value=(1, {})):
            result = reanalyze.reanalyze_article(1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["analysis_status"], "failed")
        self.assertEqual(result["analysis_error"], "model_unavailable")

    def test_analyze_article_raising_marks_failed_and_returns_ok_false(self):
        with patch("services.articles.reanalyze.load_article_for_reanalysis", return_value=dict(self.ARTICLE_ROW)), \
             patch("services.articles.reanalyze._primary_project_id_for_article", return_value=None), \
             patch("services.articles.reanalyze.analyze_article", side_effect=RuntimeError("boom")), \
             patch("services.articles.reanalyze._mark_failed") as mock_mark_failed, \
             patch("services.articles.reanalyze.save_articles") as mock_save:
            result = reanalyze.reanalyze_article(1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["analysis_status"], "failed")
        mock_mark_failed.assert_called_once()
        mock_save.assert_not_called()

    def test_save_failure_is_reported_without_raising(self):
        analysis_result = {"analysis_status": "success", "analysis_error": None}
        with patch("services.articles.reanalyze.load_article_for_reanalysis", return_value=dict(self.ARTICLE_ROW)), \
             patch("services.articles.reanalyze._primary_project_id_for_article", return_value=None), \
             patch("services.articles.reanalyze.analyze_article", return_value=analysis_result), \
             patch("services.articles.reanalyze.save_articles", side_effect=RuntimeError("db down")), \
             patch("services.articles.reanalyze._mark_failed") as mock_mark_failed:
            result = reanalyze.reanalyze_article(1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["analysis_status"], "failed")
        mock_mark_failed.assert_called_once()


class ReanalyzeArticlesBatchTests(unittest.TestCase):
    def test_runs_each_article_independently_and_collects_results(self):
        with patch("services.articles.reanalyze.reanalyze_article",
                   side_effect=lambda aid, run_id=None: {"article_id": aid, "ok": True}) as mock_single:
            results = reanalyze.reanalyze_articles([1, 2, 3])
        self.assertEqual(results, [{"article_id": 1, "ok": True}, {"article_id": 2, "ok": True}, {"article_id": 3, "ok": True}])
        self.assertEqual(mock_single.call_count, 3)

    def test_run_id_is_passed_through_to_every_article(self):
        """The analysis run tags the articles it analyzes, so per-run
        dashboard/report scoping has something to filter on."""
        with patch("services.articles.reanalyze.reanalyze_article",
                   side_effect=lambda aid, run_id=None: {"article_id": aid, "run_id": run_id}) as mock_single:
            results = reanalyze.reanalyze_articles([7, 8], run_id="run-1")
        self.assertEqual([r["run_id"] for r in results], ["run-1", "run-1"])
        self.assertEqual(mock_single.call_count, 2)


class MarkHelpersTests(unittest.TestCase):
    def test_mark_processing_swallows_db_errors(self):
        with patch("services.articles.reanalyze.db.execute", side_effect=RuntimeError("boom")):
            reanalyze.mark_processing(1)  # must not raise

    def test_mark_reprocess_requested_returns_a_timestamp_even_on_db_error(self):
        with patch("services.articles.reanalyze.db.execute", side_effect=RuntimeError("boom")):
            result = reanalyze.mark_reprocess_requested(1)
        self.assertIsInstance(result, str)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
