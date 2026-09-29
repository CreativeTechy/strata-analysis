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
            patch.object(config, 'SENTIMENT_CLASSIFIER_MODEL', 'fixture/sentiment'),
            patch.object(config, 'CLASSIFICATION_MODEL', 'fixture/classification'),
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
        self.assertEqual(result["sentiment_status"], "ran")
        self.assertEqual(result["classification_status"], "ran")
        self.assertEqual(result["category_status"], "ran")
        self.assertEqual(result["writer_tone_status"], "ran")
        self.assertEqual(result["article_tone_status"], "ran")
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

    def test_records_model_unavailable_instead_of_treating_fallback_as_neutral(self):
        with patch(
            "analysis.orchestrator.classify_article_sentiment",
            return_value={"label": "neutral", "score": 0.0, "low_confidence": True, "raw_label": None},
        ):
            result = orchestrator.analyze_article(ARTICLE)
        self.assertEqual(result["sentiment"], "neutral")
        self.assertEqual(result["sentiment_status"], "skipped_model_unavailable")

    def test_per_substage_status_survives_a_lone_classification_fallback(self):
        # writer_tone falls back (model produced no result) while category and
        # article_tone succeed - classification_status is a combined flag and
        # reads "ran" regardless, but writer_tone's own status must still say
        # it didn't run so its confidence isn't shown as genuine.
        with patch(
            "analysis.orchestrator.classification.classify_writer_tone",
            return_value={"label": "neutral", "score": 0.0, "low_confidence": True, "raw_label": None},
        ):
            result = orchestrator.analyze_article(ARTICLE)
        self.assertEqual(result["classification_status"], "ran")
        self.assertEqual(result["category_status"], "ran")
        self.assertEqual(result["writer_tone_status"], "skipped_model_unavailable")
        self.assertEqual(result["article_tone_status"], "ran")

    def test_llm_fallback_used_when_hf_stage_unavailable_and_llm_value_valid(self):
        # sentiment classifier unavailable (no result) but the same
        # structured-extraction call gave a valid sentiment - the LLM value
        # is used and recorded as 'ran_via_llm' with the llm: model id.
        extracted_with_sentiment = dict(EXTRACTED_DATA, sentiment="negative")
        with patch(
            "analysis.orchestrator.structured_extraction.extract_structured_data",
            return_value=ExtractionResult(data=extracted_with_sentiment, attempts=1),
        ), patch(
            "analysis.orchestrator.classify_article_sentiment",
            return_value={"label": "neutral", "score": 0.0, "low_confidence": True, "raw_label": None},
        ):
            result = orchestrator.analyze_article(ARTICLE)
        self.assertEqual(result["sentiment"], "negative")
        self.assertEqual(result["sentiment_status"], "ran_via_llm")
        self.assertEqual(result["sentiment_model"], f"llm:{config.LLM_PROVIDER}:{config.LLM_CHAT_MODEL}")

    def test_llm_fallback_not_used_when_no_valid_llm_value(self):
        # HF stage unavailable and the LLM gave nothing usable for sentiment
        # either (field simply absent) - behavior is unchanged from before
        # this feature existed.
        with patch(
            "analysis.orchestrator.classify_article_sentiment",
            return_value={"label": "neutral", "score": 0.0, "low_confidence": True, "raw_label": None},
        ):
            result = orchestrator.analyze_article(ARTICLE)
        self.assertEqual(result["sentiment"], "neutral")
        self.assertEqual(result["sentiment_status"], "skipped_model_unavailable")
        self.assertEqual(result["sentiment_model"], "fixture/sentiment")

    def test_llm_fallback_ignored_when_hf_stage_actually_ran(self):
        # HF sentiment classifier ran successfully - an LLM-provided value
        # must never override a real classifier result.
        extracted_with_sentiment = dict(EXTRACTED_DATA, sentiment="negative")
        with patch(
            "analysis.orchestrator.structured_extraction.extract_structured_data",
            return_value=ExtractionResult(data=extracted_with_sentiment, attempts=1),
        ):
            result = orchestrator.analyze_article(ARTICLE)
        self.assertEqual(result["sentiment"], "positive")
        self.assertEqual(result["sentiment_status"], "ran")
        self.assertEqual(result["sentiment_model"], "fixture/sentiment")

    def test_classification_model_only_stamped_llm_when_all_three_substages_used_it(self):
        extracted_with_tones = dict(
            EXTRACTED_DATA, category="news", writer_tone="critical", article_tone="critical"
        )
        unavailable = {"label": "neutral", "score": 0.0, "low_confidence": True, "raw_label": None}
        with patch(
            "analysis.orchestrator.structured_extraction.extract_structured_data",
            return_value=ExtractionResult(data=extracted_with_tones, attempts=1),
        ), patch("analysis.orchestrator.classification.classify_category", return_value=unavailable), patch(
            "analysis.orchestrator.classification.classify_writer_tone", return_value=unavailable
        ), patch(
            "analysis.orchestrator.classification.classify_article_tone", return_value=unavailable
        ):
            result = orchestrator.analyze_article(ARTICLE)
        self.assertEqual(result["category_status"], "ran_via_llm")
        self.assertEqual(result["writer_tone_status"], "ran_via_llm")
        self.assertEqual(result["article_tone_status"], "ran_via_llm")
        self.assertEqual(result["classification_model"], f"llm:{config.LLM_PROVIDER}:{config.LLM_CHAT_MODEL}")

        # Only writer_tone falls through to the LLM this time - the combined
        # classification_model column must not be stamped "llm:..." for a
        # mixed HF/LLM provenance across the three sub-stages.
        with patch(
            "analysis.orchestrator.structured_extraction.extract_structured_data",
            return_value=ExtractionResult(data=extracted_with_tones, attempts=1),
        ), patch("analysis.orchestrator.classification.classify_writer_tone", return_value=unavailable):
            mixed_result = orchestrator.analyze_article(ARTICLE)
        self.assertEqual(mixed_result["writer_tone_status"], "ran_via_llm")
        self.assertEqual(mixed_result["category_status"], "ran")
        self.assertEqual(mixed_result["classification_model"], "fixture/classification")

    def test_explicit_stage_failure_is_preserved(self):
        self.assertEqual(
            orchestrator._stage_outcome({"outcome": "failed"}, "classifier/model"),
            "failed",
        )
        self.assertEqual(
            orchestrator._combined_stage_outcome(
                ({"outcome": "ran"}, {"outcome": "failed"}),
                "classifier/model",
            ),
            "failed",
        )

    def test_combined_stage_outcome_precedence_includes_ran_via_llm(self):
        self.assertEqual(
            orchestrator._combined_stage_outcome(
                ({"outcome": "ran_via_llm"}, {"outcome": "skipped_model_unavailable"}),
                "classifier/model",
            ),
            "ran_via_llm",
        )
        self.assertEqual(
            orchestrator._combined_stage_outcome(
                ({"outcome": "ran"}, {"outcome": "ran_via_llm"}),
                "classifier/model",
            ),
            "ran",
        )
        self.assertEqual(
            orchestrator._combined_stage_outcome(
                ({"outcome": "failed"}, {"outcome": "ran_via_llm"}),
                "classifier/model",
            ),
            "failed",
        )

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
