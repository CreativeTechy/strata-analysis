"""Article relevance screening uses fast scores, safe fallbacks and overrides."""

import unittest
from unittest.mock import patch

from services.articles import relevance_screening as screening


def _row(article_id, *, override=None):
    return {
        "id": article_id,
        "title": f"Article {article_id}",
        "text": "Body",
        "content_hash": f"content-{article_id}",
        "embedding_json": None,
        "embedding_model": None,
        "embedding_source": None,
        "similarity_score": None,
        "relevance_decision": None,
        "relevance_explanation": None,
        "relevance_source": None,
        "relevance_scope_hash": None,
        "relevance_content_hash": None,
        "relevance_model": None,
        "relevance_rules_version": None,
        "manual_relevance_override": override,
        "manual_relevance_reason": "Reviewed by an editor" if override else None,
    }


class ArticleRelevanceScreeningTests(unittest.TestCase):
    def setUp(self):
        self.rows = [_row(1), _row(2), _row(3)]
        self.patchers = [
            patch.object(screening.db, "fetch_all", return_value=self.rows),
            patch.object(screening, "get_project", return_value={"id": 9, "name": "Lebanon fuel crisis", "description": "Fuel supply and prices"}),
            patch.object(screening, "_project_vector", return_value=[1.0, 0.0]),
            patch.object(screening, "_persist_screening"),
            patch.object(screening, "_record_run_screenings"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()

    def test_enforcement_excludes_clear_misses_and_keeps_uncertain_items(self):
        vectors = {1: [1.0, 0.0], 2: [0.0, 1.0], 3: [0.5, 0.8660254]}
        with patch.object(screening, "_article_vectors", return_value=vectors), \
             patch.object(screening, "_classify_borderline", return_value={
                 3: {"relevance": "uncertain", "score": 0.4, "explanation": "Needs a person."},
             }):
            result = screening.screen_project_articles(9, "run-1", mode="enforce")

        self.assertEqual(result["included_ids"], [1, 3])
        self.assertEqual(result["excluded"], 1)
        self.assertEqual(result["needs_review"], 1)
        screening._record_run_screenings.assert_called_once()

    def test_observation_records_exclusions_without_dropping_them(self):
        with patch.object(screening, "_article_vectors", return_value={1: [0.0, 1.0], 2: [0.0, 1.0], 3: [0.0, 1.0]}):
            result = screening.screen_project_articles(9, "run-2", mode="observe")
        self.assertEqual(result["excluded"], 3)
        self.assertEqual(result["included_ids"], [1, 2, 3])

    def test_missing_embeddings_fail_open_for_review(self):
        with patch.object(screening, "_article_vectors", return_value={}):
            result = screening.screen_project_articles(9, "run-3", mode="enforce")
        self.assertEqual(result["needs_review"], 3)
        self.assertEqual(result["included_ids"], [1, 2, 3])

    def test_manual_exclusion_is_authoritative_even_in_observation_mode(self):
        self.rows[:] = [_row(1, override="exclude")]
        result = screening.screen_project_articles(9, "run-4", mode="observe")
        self.assertEqual(result["included_ids"], [])
        self.assertEqual(result["results"][0]["source"], "manual")

    def test_malformed_llm_payload_is_rejected(self):
        self.assertIsNone(screening._validate_llm_results({"results": [{"id": 1, "relevance": "relevant"}]}, {1, 2}))


if __name__ == "__main__":
    unittest.main()
