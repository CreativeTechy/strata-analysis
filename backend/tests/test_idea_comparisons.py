import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.articles import idea_comparisons


class SourceLabelTests(unittest.TestCase):
    def test_prefers_source_url_host(self):
        row = {"source_url": "https://www.eia.gov/petroleum/report", "url": "https://twitter.com/x/1", "source": "file.pdf"}
        self.assertEqual(idea_comparisons._source_label(row), "eia.gov")

    def test_falls_back_to_url_host_without_www(self):
        row = {"source_url": "", "url": "https://twitter.com/someuser/status/1", "source": ""}
        self.assertEqual(idea_comparisons._source_label(row), "twitter.com")

    def test_falls_back_to_document_filename(self):
        row = {"source_url": "", "url": "", "source": "quarterly-report.pdf"}
        self.assertEqual(idea_comparisons._source_label(row), "quarterly-report.pdf")

    def test_unknown_when_nothing_present(self):
        self.assertEqual(idea_comparisons._source_label({}), "Unknown source")


class GroupAndQualifyClustersTests(unittest.TestCase):
    def _rows(self):
        return [
            {
                "idea_cluster_id": 1, "idea": "petrol price", "type": "issue", "frequency_estimate": 3,
                "article_id": 10, "title": "EIA report", "url": "", "source": "", "source_url": "https://www.eia.gov/a",
                "published": None, "summary": "Fuel costs.", "value": "$98/barrel",
            },
            {
                "idea_cluster_id": 1, "idea": "petrol price", "type": "issue", "frequency_estimate": 3,
                "article_id": 11, "title": "Tweet", "url": "https://twitter.com/x/1", "source": "", "source_url": "",
                "published": None, "summary": "People are angry.", "value": "$120/barrel",
            },
            {
                # Same source repeating its own idea - must not count as a second distinct source.
                "idea_cluster_id": 2, "idea": "single source idea", "type": "praise", "frequency_estimate": 2,
                "article_id": 12, "title": "A", "url": "", "source": "", "source_url": "https://www.eia.gov/a",
                "published": None, "summary": "", "value": "",
            },
            {
                "idea_cluster_id": 2, "idea": "single source idea", "type": "praise", "frequency_estimate": 2,
                "article_id": 13, "title": "B", "url": "", "source": "", "source_url": "https://www.eia.gov/b",
                "published": None, "summary": "", "value": "",
            },
        ]

    def test_diverging_values_across_distinct_sources_are_flagged(self):
        clusters = idea_comparisons._group_clusters(self._rows())
        qualifying = idea_comparisons._qualifying_clusters(clusters, limit=10)
        self.assertEqual(len(qualifying), 1)
        self.assertEqual(qualifying[0]["idea_cluster_id"], 1)
        self.assertTrue(qualifying[0]["diverges"])

    def test_single_distinct_source_is_excluded_even_with_two_articles(self):
        clusters = idea_comparisons._group_clusters(self._rows())
        qualifying = idea_comparisons._qualifying_clusters(clusters, limit=10)
        self.assertNotIn(2, [c["idea_cluster_id"] for c in qualifying])


class GenerateIdeaComparisonsTests(unittest.TestCase):
    def test_writes_one_row_per_qualifying_cluster_and_uses_synthesized_summary(self):
        rows = GroupAndQualifyClustersTests()._rows()[:2]
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", "postgres://x"), \
             patch("services.articles.idea_comparisons._cluster_candidates", return_value=rows), \
             patch("services.articles.idea_comparisons.chat_completion", return_value='{"summary": "eia.gov says $98, Twitter says $120."}'), \
             patch("services.articles.idea_comparisons.db.execute") as mock_execute:
            written = idea_comparisons.generate_idea_comparisons(project_id=1)
        self.assertEqual(written, 1)
        mock_execute.assert_called_once()
        sql, params = mock_execute.call_args[0]
        self.assertIn("insert into idea_comparisons", sql)
        self.assertEqual(params[2], "petrol price")
        self.assertTrue(params[4])  # diverges
        self.assertEqual(params[6], "eia.gov says $98, Twitter says $120.")

    def test_unparsable_llm_response_still_saves_the_card_without_a_summary(self):
        rows = GroupAndQualifyClustersTests()._rows()[:2]
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", "postgres://x"), \
             patch("services.articles.idea_comparisons._cluster_candidates", return_value=rows), \
             patch("services.articles.idea_comparisons.chat_completion", return_value="not json"), \
             patch("services.articles.idea_comparisons.db.execute") as mock_execute:
            written = idea_comparisons.generate_idea_comparisons(project_id=1)
        self.assertEqual(written, 1)
        params = mock_execute.call_args[0][1]
        self.assertIsNone(params[6])

    def test_noop_without_database(self):
        with patch("services.articles.idea_comparisons.config.DATABASE_URL", ""), \
             patch("services.articles.idea_comparisons.db.execute") as mock_execute:
            written = idea_comparisons.generate_idea_comparisons(project_id=1)
        self.assertEqual(written, 0)
        mock_execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
