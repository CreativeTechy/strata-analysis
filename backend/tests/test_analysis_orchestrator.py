import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

import config
from analysis import orchestrator
from analysis.structured_extraction import ExtractionResult

ARTICLE = {"title": "New EV Review", "text": "x" * 300, "url": "https://example.com/a"}

EXTRACTED_DATA = {
    "topic": "ev review",
    "summary": "A glowing review.",
    "positive_feedback": ["great range"],
    "negative_feedback": [],
    "nice_to_have_features": [],
    "complaints": [],
    "great_features": [],
    "comfort_issues": [],
    "performance_feedback": [],
    "price_value_feedback": [],
    "maintenance_reliability_feedback": [],
    "technology_feedback": [],
    "safety_feedback": [],
    "key_points": [],
    "risks": [],
    "opportunities": [],
    "organizations": ["Acme Motors"],
    "entities": ["Model X"],
    "topics": ["ev"],
    "relevance_score": 8,
    "people_opinions": [],
    "frequent_ideas": [],
}


class AnalyzeArticleTests(unittest.TestCase):
    def setUp(self):
        self._patchers = [
            patch(
                "analysis.orchestrator.structured_extraction.extract_structured_data",
                return_value=ExtractionResult(data=dict(EXTRACTED_DATA), attempts=1),
            ),
            patch(
                "analysis.orchestrator.classify_article_sentiment",
                return_value={"label": "positive", "score": 0.9, "low_confidence": False},
            ),
            patch(
                "analysis.orchestrator.classification.classify_category",
                return_value={"label": "review", "score": 0.9, "low_confidence": False},
            ),
            patch(
                "analysis.orchestrator.classification.classify_writer_tone",
                return_value={"label": "enthusiastic", "score": 0.9, "low_confidence": False},
            ),
            patch(
                "analysis.orchestrator.classification.classify_article_tone",
                return_value={"label": "positive", "score": 0.9, "low_confidence": False},
            ),
            patch(
                "analysis.orchestrator.language.detect_language",
                return_value={"language": "en", "score": 0.98, "low_confidence": False},
            ),
            patch("analysis.orchestrator.entity_extraction.extract_entities", return_value=None),
            patch("analysis.orchestrator.get_embedding", return_value={}),
        ]
        self._mocks = [p.start() for p in self._patchers]

    def tearDown(self):
        for p in self._patchers:
            p.stop()

    def test_merges_every_stage_into_the_legacy_article_shape(self):
        result = orchestrator.analyze_article(ARTICLE)
        self.assertIsNotNone(result)
        self.assertEqual(result["summary"], "A glowing review.")
        self.assertEqual(result["sentiment"], "positive")
        self.assertEqual(result["overall_sentiment"], "positive")
        self.assertEqual(result["article_category"], "review")
        self.assertEqual(result["category"], "review")
        self.assertEqual(result["writer_tone"], "enthusiastic")
        self.assertEqual(result["article_tone"], "positive")
        # writer_tone="enthusiastic" and article_tone="positive" are both
        # non-neutral and differ, so the deterministic merge is "mixed".
        self.assertEqual(result["overall_tone"], "mixed")
        self.assertEqual(result["organizations"], ["Acme Motors"])
        self.assertEqual(result["brands"], ["Acme Motors"])
        self.assertEqual(result["entities"], ["Model X"])
        self.assertEqual(result["car_models"], ["Model X"])
        self.assertEqual(result["relevance_score"], 8)
        self.assertIn("insight_json", result)
        self.assertEqual(result["insight_json"]["summary"], "A glowing review.")

    def test_per_stage_metadata_is_persisted(self):
        result = orchestrator.analyze_article(ARTICLE)
        self.assertEqual(result["sentiment_score"], 0.9)
        self.assertFalse(result["sentiment_low_confidence"])
        self.assertEqual(result["category_confidence"], 0.9)
        self.assertEqual(result["writer_tone_confidence"], 0.9)
        self.assertEqual(result["article_tone_confidence"], 0.9)
        self.assertEqual(result["source_language"], "en")
        self.assertEqual(result["source_language_confidence"], 0.98)
        self.assertEqual(result["analysis_status"], "success")
        self.assertIsNone(result["analysis_error"])
        self.assertEqual(result["analysis_attempt_count"], 1)
        self.assertIsNotNone(result["analysis_started_at"])
        self.assertIsNotNone(result["analysis_finished_at"])
        for model_field in ("sentiment_model", "classification_model", "extraction_model"):
            self.assertTrue(result[model_field])
        # extraction is now provider-backed (no dedicated local model), so its
        # identifier is "<provider>:<model>" rather than a bare model name.
        self.assertIn(":", result["extraction_model"])
        self.assertTrue(result["extraction_model"].startswith(f"{config.LLM_PROVIDER}:"))

    def test_entity_extraction_override_replaces_extraction_entities_when_enabled(self):
        with patch(
            "analysis.orchestrator.entity_extraction.extract_entities",
            return_value={"organizations": ["Other Corp"], "entities": ["Widget"]},
        ):
            result = orchestrator.analyze_article(ARTICLE)
        self.assertEqual(result["organizations"], ["Other Corp"])
        self.assertEqual(result["entities"], ["Widget"])

    def test_extraction_failure_returns_neutral_content_with_failed_status(self):
        """Structured extraction failing outright no longer means None -
        analyze_article() always returns a dict so the failure itself is
        persisted (analysis_status/analysis_error), not silently dropped."""
        with patch(
            "analysis.orchestrator.structured_extraction.extract_structured_data",
            return_value=ExtractionResult(failed=True, reason="model_unavailable", attempts=1),
        ):
            result = orchestrator.analyze_article(ARTICLE)
        self.assertIsNotNone(result)
        self.assertEqual(result["analysis_status"], "failed")
        self.assertEqual(result["analysis_error"], "model_unavailable")
        self.assertEqual(result["summary"], "")
        self.assertEqual(result["positive_feedback"], [])
        self.assertEqual(result["relevance_score"], 0)
        # Sentiment/tone/category still run even when extraction fails - only
        # the extracted content itself is neutral.
        self.assertEqual(result["sentiment"], "positive")

    def test_embedding_fields_default_to_empty_when_embedding_unavailable(self):
        result = orchestrator.analyze_article(ARTICLE)
        self.assertEqual(result["embedding_json"], [])
        self.assertEqual(result["embedding_model"], "")

    def test_embedding_result_is_merged_when_available(self):
        with patch(
            "analysis.orchestrator.get_embedding",
            return_value={"embedding_json": [0.1, 0.2], "embedding_model": "fake-model", "embedding_source": "test", "embedded_at": "now"},
        ):
            result = orchestrator.analyze_article(ARTICLE)
        self.assertEqual(result["embedding_json"], [0.1, 0.2])
        self.assertEqual(result["embedding_model"], "fake-model")


if __name__ == "__main__":
    unittest.main()
