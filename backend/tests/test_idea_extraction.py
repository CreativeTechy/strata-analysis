import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from llm_client import LLMConnectionError
from services.competitors import idea_extraction


class _Extraction:
    def __init__(self, data=None, failed=False):
        self.data = data
        self.failed = failed


class ExtractFrequentIdeasForDocumentsTests(unittest.TestCase):
    def test_noop_without_document_ids(self):
        with patch("services.competitors.idea_extraction.db.fetch_all") as mock_fetch_all:
            written = idea_extraction.extract_frequent_ideas_for_documents(1, [])
        self.assertEqual(written, 0)
        mock_fetch_all.assert_not_called()

    def test_only_selects_articles_not_already_successfully_extracted(self):
        with patch("services.competitors.idea_extraction.db.fetch_all", return_value=[]) as mock_fetch_all:
            idea_extraction.extract_frequent_ideas_for_documents(1, [10, 11])
        sql, params = mock_fetch_all.call_args[0]
        self.assertIn("coalesce(a.analysis_status, 'pending') != 'success'", sql)
        self.assertEqual(params, (1, [10, 11]))

    def test_successful_extraction_updates_article_and_links_idea_clusters(self):
        articles = [{"id": 5, "title": "Rival cuts prices", "text": "Full body text."}]
        extraction = _Extraction(data={
            "summary": "Rival cut prices by 10%.",
            "frequent_ideas": [{"idea": "price cut", "type": "issue", "value": "10%"}],
        })
        with patch("services.competitors.idea_extraction.db.fetch_all", return_value=articles), \
             patch("services.competitors.idea_extraction.extract_structured_data", return_value=extraction), \
             patch("services.competitors.idea_extraction.db.execute") as mock_execute, \
             patch("services.competitors.idea_extraction._replace_idea_clusters_for_article") as mock_link:
            written = idea_extraction.extract_frequent_ideas_for_documents(1, [10])
        self.assertEqual(written, 1)
        mock_link.assert_called_once_with(5, 1, extraction.data["frequent_ideas"])
        update_sql, update_params = mock_execute.call_args[0]
        self.assertIn("analysis_status = 'success'", update_sql)
        self.assertEqual(update_params, ("Rival cut prices by 10%.", 5))

    def test_failed_extraction_marks_article_failed_without_linking(self):
        articles = [{"id": 6, "title": "t", "text": "x"}]
        extraction = _Extraction(failed=True)
        extraction.reason = "invalid_json"
        with patch("services.competitors.idea_extraction.db.fetch_all", return_value=articles), \
             patch("services.competitors.idea_extraction.extract_structured_data", return_value=extraction), \
             patch("services.competitors.idea_extraction.db.execute") as mock_execute, \
             patch("services.competitors.idea_extraction._replace_idea_clusters_for_article") as mock_link:
            written = idea_extraction.extract_frequent_ideas_for_documents(1, [10])
        self.assertEqual(written, 0)
        mock_link.assert_not_called()
        update_sql, update_params = mock_execute.call_args[0]
        self.assertIn("analysis_status = 'failed'", update_sql)
        self.assertEqual(update_params, ("invalid_json", 6))

    def test_one_bad_article_does_not_stop_the_rest(self):
        articles = [{"id": 1, "title": "a", "text": "x"}, {"id": 2, "title": "b", "text": "y"}]
        good = _Extraction(data={"summary": "s", "frequent_ideas": []})
        with patch("services.competitors.idea_extraction.db.fetch_all", return_value=articles), \
             patch(
                 "services.competitors.idea_extraction.extract_structured_data",
                 side_effect=[RuntimeError("boom"), good],
             ), \
             patch("services.competitors.idea_extraction.db.execute"), \
             patch("services.competitors.idea_extraction._replace_idea_clusters_for_article") as mock_link:
            written = idea_extraction.extract_frequent_ideas_for_documents(1, [10])
        self.assertEqual(written, 1)
        mock_link.assert_called_once_with(2, 1, [])

    def test_fatal_provider_error_propagates_instead_of_being_swallowed(self):
        articles = [{"id": 1, "title": "a", "text": "x"}, {"id": 2, "title": "b", "text": "y"}]
        with patch("services.competitors.idea_extraction.db.fetch_all", return_value=articles), \
             patch(
                 "services.competitors.idea_extraction.extract_structured_data",
                 side_effect=LLMConnectionError("model server unreachable"),
             ), \
             patch("services.competitors.idea_extraction.db.execute"), \
             patch("services.competitors.idea_extraction._replace_idea_clusters_for_article") as mock_link:
            with self.assertRaises(LLMConnectionError):
                idea_extraction.extract_frequent_ideas_for_documents(1, [10])
        mock_link.assert_not_called()


if __name__ == "__main__":
    unittest.main()
