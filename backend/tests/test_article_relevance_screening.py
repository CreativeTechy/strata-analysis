"""Article relevance screening uses fast scores, safe fallbacks and overrides."""

import unittest
from unittest.mock import MagicMock, patch

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
        vectors = {1: [1.0, 0.0], 2: [0.0, 1.0], 3: [0.75, 0.6614378]}
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

    def test_article_ids_restricts_the_query_to_that_set(self):
        with patch.object(screening, "_article_vectors", return_value={1: [1.0, 0.0]}):
            screening.screen_project_articles(9, "run-6", mode="enforce", article_ids=[1])
        query, params = screening.db.fetch_all.call_args[0]
        self.assertIn("a.id = any", query)
        self.assertEqual(params, (9, [1]))

    def test_empty_article_ids_skips_the_database_query(self):
        result = screening.screen_project_articles(9, "run-7", mode="enforce", article_ids=[])
        screening.db.fetch_all.assert_not_called()
        self.assertEqual(result, {"mode": "enforce", "results": [], "included_ids": [], "screened": 0,
                                   "included": 0, "excluded": 0, "needs_review": 0})

    def test_outage_fallback_is_not_persisted_as_a_cached_decision(self):
        """F003: an embedding-model outage must not permanently turn
        screening off for the articles it touched."""
        with patch.object(screening, "_article_vectors", return_value={}):
            screening.screen_project_articles(9, "run-8", mode="enforce")
        screening._persist_screening.assert_not_called()

    def test_llm_outage_is_tagged_separately_from_a_genuine_uncertain_answer(self):
        vectors = {1: [1.0, 0.0], 2: [0.0, 1.0], 3: [0.75, 0.6614378]}
        with patch.object(screening, "_article_vectors", return_value=vectors), \
             patch.object(screening, "_classify_borderline", return_value={
                 3: {"relevance": "uncertain", "score": 0.0, "explanation": "unavailable", "unavailable": True},
             }):
            result = screening.screen_project_articles(9, "run-9", mode="enforce")
        borderline_result = next(item for item in result["results"] if item["article_id"] == 3)
        self.assertEqual(borderline_result["source"], "llm_unavailable")
        # Only the two clearly-scored embedding articles get cached - the
        # outage-affected one must not.
        self.assertEqual(screening._persist_screening.call_count, 2)

    def test_a_genuine_llm_uncertain_answer_is_still_cached(self):
        vectors = {1: [1.0, 0.0], 2: [0.0, 1.0], 3: [0.75, 0.6614378]}
        with patch.object(screening, "_article_vectors", return_value=vectors), \
             patch.object(screening, "_classify_borderline", return_value={
                 3: {"relevance": "uncertain", "score": 0.4, "explanation": "Needs a person."},
             }):
            result = screening.screen_project_articles(9, "run-10", mode="enforce")
        borderline_result = next(item for item in result["results"] if item["article_id"] == 3)
        self.assertEqual(borderline_result["source"], "llm")
        self.assertEqual(screening._persist_screening.call_count, 3)

    def test_should_cancel_aborts_before_the_borderline_llm_batch(self):
        """F005: a stop request must land before the slow, blocking LLM
        batch call, not only after screening finishes entirely."""
        vectors = {1: [1.0, 0.0], 2: [0.0, 1.0], 3: [0.75, 0.6614378]}
        with patch.object(screening, "_article_vectors", return_value=vectors), \
             patch.object(screening, "_classify_borderline") as classify:
            with self.assertRaises(screening.ScreeningCancelled):
                screening.screen_project_articles(9, "run-11", mode="enforce", should_cancel=lambda: True)
        classify.assert_not_called()
        screening._record_run_screenings.assert_not_called()

    def test_should_cancel_aborts_before_embedding(self):
        with patch.object(screening, "_article_vectors", side_effect=screening.ScreeningCancelled()):
            with self.assertRaises(screening.ScreeningCancelled):
                screening.screen_project_articles(9, "run-12", mode="enforce", should_cancel=lambda: True)


class ArticleVectorsCancellationTests(unittest.TestCase):
    def test_raises_between_embedding_batches_when_cancelled(self):
        rows = [{"id": i, "title": "t", "text": "body", "embedding_json": None,
                 "embedding_model": None, "embedding_source": None} for i in range(3)]
        with patch.object(screening, "get_embeddings", return_value=[]):
            with self.assertRaises(screening.ScreeningCancelled):
                screening._article_vectors(rows, should_cancel=lambda: True)

    def test_does_not_raise_when_not_cancelled(self):
        rows = [{"id": 1, "title": "t", "text": "body", "embedding_json": None,
                 "embedding_model": None, "embedding_source": None}]
        with patch.object(screening, "get_embeddings", return_value=[{"embedding_json": [1.0, 0.0]}]), \
             patch.object(screening.db, "transaction") as mock_transaction:
            mock_transaction.return_value.__enter__.return_value = MagicMock()
            vectors = screening._article_vectors(rows, should_cancel=lambda: False)
        self.assertEqual(vectors, {1: [1.0, 0.0]})


class ProjectRelevanceSnapshotIdsTests(unittest.TestCase):
    """F001/F002: the evidence snapshot must cover the whole project corpus
    (minus real exclusions), not just one run's candidate set - and a manual
    override must apply regardless of mode or candidate status."""

    def setUp(self):
        self.patchers = [
            patch.object(screening, "get_project", return_value={"id": 9, "name": "p"}),
            patch.object(screening, "_scope_hash", return_value="scope-1"),
            patch.object(screening, "_rules_version", return_value="rules-1"),
            patch.object(screening.config, "EMBEDDING_MODEL", "model-x"),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()

    @staticmethod
    def _row(article_id, *, decision=None, content_hash="content-1", actual_content_hash="content-1",
             override=None):
        return {
            "article_id": article_id,
            "relevance_decision": decision,
            "relevance_scope_hash": "scope-1",
            "relevance_content_hash": content_hash,
            "relevance_model": "model-x",
            "relevance_rules_version": "rules-1",
            "manual_relevance_override": override,
            "content_hash": actual_content_hash,
        }

    def test_no_rows_means_no_filter(self):
        with patch.object(screening.db, "fetch_all", return_value=[]):
            self.assertIsNone(screening.project_relevance_snapshot_ids(9, "enforce"))

    def test_observe_mode_with_no_overrides_needs_no_filter(self):
        rows = [self._row(1, decision="excluded"), self._row(2, decision="accepted")]
        with patch.object(screening.db, "fetch_all", return_value=rows):
            self.assertIsNone(screening.project_relevance_snapshot_ids(9, "observe"))

    def test_enforce_mode_drops_a_validly_cached_excluded_article(self):
        rows = [self._row(1, decision="excluded"), self._row(2, decision="accepted")]
        with patch.object(screening.db, "fetch_all", return_value=rows):
            result = screening.project_relevance_snapshot_ids(9, "enforce")
        self.assertEqual(result, [2])

    def test_enforce_mode_fails_open_on_a_stale_cached_exclusion(self):
        """A decision cached against a content hash that no longer matches
        (the article's text changed since) must not keep excluding it."""
        rows = [self._row(1, decision="excluded", content_hash="old-hash", actual_content_hash="new-hash")]
        with patch.object(screening.db, "fetch_all", return_value=rows):
            result = screening.project_relevance_snapshot_ids(9, "enforce")
        self.assertEqual(result, [1])

    def test_manual_exclude_always_applies_even_outside_enforce_mode(self):
        rows = [self._row(1, decision="accepted", override="exclude"), self._row(2, decision="accepted")]
        with patch.object(screening.db, "fetch_all", return_value=rows):
            result = screening.project_relevance_snapshot_ids(9, "observe")
        self.assertEqual(result, [2])

    def test_manual_include_always_applies_even_in_enforce_mode(self):
        rows = [self._row(1, decision="excluded", override="include")]
        with patch.object(screening.db, "fetch_all", return_value=rows):
            result = screening.project_relevance_snapshot_ids(9, "enforce")
        self.assertEqual(result, [1])


if __name__ == "__main__":
    unittest.main()
