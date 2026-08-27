import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.articles import idea_clustering


class ReplaceIdeaClustersForArticleTests(unittest.TestCase):
    def test_noop_without_project_id(self):
        with patch("services.articles.idea_clustering._table_exists", return_value=True):
            with patch("services.articles.idea_clustering.db.execute") as mock_execute, \
                 patch("services.articles.idea_clustering.db.fetch_all") as mock_fetch_all:
                idea_clustering._replace_idea_clusters_for_article(1, None, [{"idea": "x"}])
        mock_execute.assert_not_called()
        mock_fetch_all.assert_not_called()

    def test_noop_when_idea_clusters_table_missing(self):
        with patch("services.articles.idea_clustering._table_exists", return_value=False):
            with patch("services.articles.idea_clustering.db.execute") as mock_execute:
                idea_clustering._replace_idea_clusters_for_article(1, 2, [{"idea": "x"}])
        mock_execute.assert_not_called()

    def test_unlinks_then_relinks_and_recomputes_frequency(self):
        with patch("services.articles.idea_clustering._table_exists", return_value=True), \
             patch("services.articles.idea_clustering.db.fetch_all", return_value=[{"idea_cluster_id": 9}]), \
             patch("services.articles.idea_clustering.db.fetch_one", return_value={"id": 42}), \
             patch("services.articles.idea_clustering.db.execute") as mock_execute:
            idea_clustering._replace_idea_clusters_for_article(
                1, 2, [{"idea": "charging is slow", "type": "complaint", "category": "charging"}]
            )
        sqls = [c.args[0] for c in mock_execute.call_args_list]
        self.assertTrue(any("delete from idea_cluster_articles" in s for s in sqls))
        self.assertTrue(any("insert into idea_cluster_articles" in s for s in sqls))
        # both the previously-linked cluster (9) and the newly-linked one (42)
        # must have their frequency recomputed, even though they're different ids.
        recompute_calls = [c for c in mock_execute.call_args_list if "frequency_estimate = (" in c.args[0]]
        recomputed_ids = {c.args[1][0] for c in recompute_calls}
        self.assertEqual(recomputed_ids, {9, 42})

    def test_invalid_idea_type_falls_back_to_issue(self):
        with patch("services.articles.idea_clustering._table_exists", return_value=True), \
             patch("services.articles.idea_clustering.db.fetch_all", return_value=[]), \
             patch("services.articles.idea_clustering.db.fetch_one", return_value={"id": 1}) as mock_fetch_one, \
             patch("services.articles.idea_clustering.db.execute"):
            idea_clustering._replace_idea_clusters_for_article(1, 2, [{"idea": "x", "type": "bogus"}])
        _, params = mock_fetch_one.call_args[0]
        self.assertEqual(params[2], "issue")

    def test_db_error_is_caught_and_logged_not_raised(self):
        with patch("services.articles.idea_clustering._table_exists", return_value=True):
            with patch("services.articles.idea_clustering.db.fetch_all", side_effect=RuntimeError("boom")):
                idea_clustering._replace_idea_clusters_for_article(1, 2, [{"idea": "x"}])  # must not raise


class ResolveIdeaClusterIdTests(unittest.TestCase):
    """Zero prior coverage of the attach-or-create logic itself (only the
    orchestrator above was tested) - added here since the module is now
    small enough to pin its exact-match/embedding-fallback branches directly."""

    def test_exact_normalized_match_reuses_the_existing_cluster(self):
        with patch("services.articles.idea_clustering.db.fetch_one", return_value={"id": 7}) as mock_fetch_one, \
             patch("services.articles.idea_clustering.db.execute") as mock_execute:
            result = idea_clustering._resolve_idea_cluster_id(1, "charging is slow", "complaint", "charging")
        self.assertEqual(result, 7)
        # touched (last_seen_at bump), not re-inserted
        mock_execute.assert_called_once()
        self.assertIn("idea_clusters set last_seen_at", mock_execute.call_args[0][0])

    def test_no_match_and_no_embedding_falls_back_to_exact_insert_only(self):
        with patch("services.articles.idea_clustering.db.fetch_one", side_effect=[None, {"id": 3}]), \
             patch("services.articles.idea_clustering.get_embedding", return_value={}):
            result = idea_clustering._resolve_idea_cluster_id(1, "new idea", "issue", "")
        self.assertEqual(result, 3)


class ResolveSegmentLabelTests(unittest.TestCase):
    def test_unknown_short_circuits_without_touching_the_database(self):
        with patch("services.articles.idea_clustering._table_exists") as mock_table_exists:
            result = idea_clustering._resolve_segment_label("unknown")
        self.assertEqual(result, "unknown")
        mock_table_exists.assert_not_called()

    def test_missing_taxonomy_table_returns_the_raw_text_unchanged(self):
        with patch("services.articles.idea_clustering._table_exists", return_value=False):
            result = idea_clustering._resolve_segment_label("laid off")
        self.assertEqual(result, "laid off")

    def test_exact_match_reuses_the_canonical_label(self):
        with patch("services.articles.idea_clustering._table_exists", return_value=True), \
             patch("services.articles.idea_clustering.db.fetch_one", return_value={"canonical_label": "Unemployed"}), \
             patch("services.articles.idea_clustering.db.execute") as mock_execute:
            result = idea_clustering._resolve_segment_label("laid off")
        self.assertEqual(result, "Unemployed")
        mock_execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
