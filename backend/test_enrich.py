import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
import enrich


class NormalizeSentimentTests(unittest.TestCase):
    def test_exact_matches_pass_through(self):
        for value in ("positive", "negative", "mixed", "neutral"):
            self.assertEqual(enrich._normalize_sentiment(value), value)

    def test_trailing_punctuation_and_case_are_tolerated(self):
        self.assertEqual(enrich._normalize_sentiment("Positive."), "positive")
        self.assertEqual(enrich._normalize_sentiment("NEGATIVE"), "negative")

    def test_qualified_phrases_map_to_the_label_they_lean_toward(self):
        self.assertEqual(enrich._normalize_sentiment("mostly positive"), "positive")
        self.assertEqual(enrich._normalize_sentiment("negative overall"), "negative")
        self.assertEqual(enrich._normalize_sentiment("mixed sentiment"), "mixed")
        self.assertEqual(enrich._normalize_sentiment("somewhat positive"), "positive")

    def test_phrases_mentioning_both_directions_are_mixed(self):
        self.assertEqual(enrich._normalize_sentiment("positive and negative"), "mixed")

    def test_unrecognized_or_empty_values_fall_back_to_neutral(self):
        self.assertEqual(enrich._normalize_sentiment("unclear"), "neutral")
        self.assertEqual(enrich._normalize_sentiment(""), "neutral")
        self.assertEqual(enrich._normalize_sentiment(None), "neutral")


class ValidateEnrichmentTests(unittest.TestCase):
    def _payload(self, **overrides):
        payload = {
            "summary": "The reviewer liked the car overall.",
            "article_category": "review",
            "overall_sentiment": "positive",
        }
        payload.update(overrides)
        return payload

    def test_missing_summary_is_treated_as_invalid(self):
        self.assertIsNone(enrich._validate_enrichment({"overall_sentiment": "positive"}))

    def test_non_dict_payload_is_invalid(self):
        self.assertIsNone(enrich._validate_enrichment("not a dict"))

    def test_loose_sentiment_values_are_normalized_end_to_end(self):
        validated = enrich._validate_enrichment(self._payload(overall_sentiment="mostly positive"))
        self.assertEqual(validated["overall_sentiment"], "positive")
        self.assertEqual(validated["sentiment"], "positive")
        self.assertEqual(validated["insight_json"]["overall_sentiment"], "positive")

    def test_neutral_complaint_category_is_forced_negative(self):
        validated = enrich._validate_enrichment(
            self._payload(overall_sentiment="neutral", article_category="complaint")
        )
        self.assertEqual(validated["overall_sentiment"], "negative")

    def test_output_shape_is_unchanged(self):
        validated = enrich._validate_enrichment(self._payload())
        self.assertEqual(set(validated.keys()), set(enrich.DEFAULT_ENRICHMENT.keys()))


class SentimentClassifierIntegrationTests(unittest.TestCase):
    """Covers _apply_sentiment_classifier, the enrich.py call site that wires
    the ENABLE_SENTIMENT_CLASSIFIER toggle into the enrichment payload."""

    def setUp(self):
        self._original_enabled = config.ENABLE_SENTIMENT_CLASSIFIER
        self._original_min_score = config.SENTIMENT_CLASSIFIER_MIN_SCORE

    def tearDown(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = self._original_enabled
        config.SENTIMENT_CLASSIFIER_MIN_SCORE = self._original_min_score

    def _validated(self, sentiment="neutral"):
        return dict(enrich._validate_enrichment({
            "summary": "A calm, factual write-up.",
            "overall_sentiment": sentiment,
        }))

    def test_disabled_by_default_keeps_the_llm_sentiment(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = False
        validated = self._validated(sentiment="positive")
        with patch("enrich.classify_sentiment") as mocked:
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        mocked.assert_not_called()
        self.assertEqual(validated["overall_sentiment"], "positive")

    def test_enabled_and_confident_classification_replaces_the_llm_sentiment(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        config.SENTIMENT_CLASSIFIER_MIN_SCORE = 0.6
        # LLM said "mixed" - the classifier's verdict should win once enabled,
        # since sentiment is no longer LLM-driven when the toggle is on.
        validated = self._validated(sentiment="mixed")
        with patch("enrich.classify_sentiment", return_value={"label": "positive", "score": 0.92}):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "positive")
        self.assertEqual(validated["sentiment"], "positive")
        self.assertEqual(validated["insight_json"]["overall_sentiment"], "positive")

    def test_low_confidence_classification_falls_back_to_the_llm_sentiment(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        config.SENTIMENT_CLASSIFIER_MIN_SCORE = 0.6
        validated = self._validated(sentiment="negative")
        with patch("enrich.classify_sentiment", return_value={"label": "positive", "score": 0.3}):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "negative")

    def test_classifier_returning_none_falls_back_to_the_llm_sentiment(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        validated = self._validated(sentiment="positive")
        with patch("enrich.classify_sentiment", return_value=None):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "positive")

    def test_classifier_raising_falls_back_to_the_llm_sentiment_without_crashing(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        validated = self._validated(sentiment="positive")
        with patch("enrich.classify_sentiment", side_effect=RuntimeError("boom")):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "positive")


class EnrichArticleFallbackTests(unittest.TestCase):
    def test_llm_failure_returns_none_so_the_pipeline_can_fall_back(self):
        with patch("enrich.chat_completion", side_effect=RuntimeError("boom")):
            self.assertIsNone(enrich.enrich_article({"title": "t", "text": "x" * 300}))

    def test_invalid_json_from_the_llm_returns_none(self):
        with patch("enrich.chat_completion", return_value="not json"):
            self.assertIsNone(enrich.enrich_article({"title": "t", "text": "x" * 300}))


class EnrichArticleSentimentToggleTests(unittest.TestCase):
    """End-to-end: enrich_article() with the LLM and embeddings mocked out,
    checking the ENABLE_SENTIMENT_CLASSIFIER toggle picks the right source
    for `overall_sentiment` while every other field stays LLM-produced."""

    LLM_JSON = json.dumps({
        "summary": "A glowing review of the new model.",
        "topic": "new model launch",
        "article_category": "review",
        "overall_sentiment": "neutral",
        "writer_tone": "positive",
        "article_tone": "positive",
        "positive_feedback": ["great range"],
    })

    def setUp(self):
        self._original_enabled = config.ENABLE_SENTIMENT_CLASSIFIER
        self._patchers = [
            patch("enrich.chat_completion", return_value=self.LLM_JSON),
            patch("enrich.get_embedding", return_value={}),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = self._original_enabled
        for p in self._patchers:
            p.stop()

    def test_disabled_uses_the_llm_sentiment(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = False
        with patch("enrich.classify_sentiment") as mocked:
            result = enrich.enrich_article({"title": "t", "text": "x" * 300})
        mocked.assert_not_called()
        self.assertEqual(result["overall_sentiment"], "neutral")
        self.assertEqual(result["topic"], "new model launch")
        self.assertEqual(result["writer_tone"], "positive")

    def test_enabled_uses_the_classifier_sentiment_and_keeps_other_fields(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        with patch("enrich.classify_sentiment", return_value={"label": "positive", "score": 0.95}):
            result = enrich.enrich_article({"title": "t", "text": "x" * 300})
        self.assertEqual(result["overall_sentiment"], "positive")
        self.assertEqual(result["sentiment"], "positive")
        # Everything else stays exactly what the LLM produced.
        self.assertEqual(result["topic"], "new model launch")
        self.assertEqual(result["article_category"], "review")
        self.assertEqual(result["writer_tone"], "positive")
        self.assertEqual(result["positive_feedback"], ["great range"])

    def test_enabled_but_classifier_unavailable_still_returns_a_full_payload(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        with patch("enrich.classify_sentiment", return_value=None):
            result = enrich.enrich_article({"title": "t", "text": "x" * 300})
        self.assertIsNotNone(result)
        self.assertEqual(result["overall_sentiment"], "neutral")


if __name__ == "__main__":
    unittest.main()
