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
    def setUp(self):
        self._original_model = config.SENTIMENT_CLASSIFIER_MODEL
        self._original_min_score = config.SENTIMENT_CLASSIFIER_MIN_SCORE

    def tearDown(self):
        config.SENTIMENT_CLASSIFIER_MODEL = self._original_model
        config.SENTIMENT_CLASSIFIER_MIN_SCORE = self._original_min_score

    def _validated(self, sentiment="neutral"):
        return dict(enrich._validate_enrichment({
            "summary": "A calm, factual write-up.",
            "overall_sentiment": sentiment,
        }))

    def test_noop_when_classifier_is_not_configured(self):
        config.SENTIMENT_CLASSIFIER_MODEL = ""
        validated = self._validated()
        with patch("enrich.classify_sentiment") as mocked:
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        mocked.assert_not_called()
        self.assertEqual(validated["overall_sentiment"], "neutral")

    def test_confident_non_neutral_classification_promotes_neutral_sentiment(self):
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/sentiment-model"
        config.SENTIMENT_CLASSIFIER_MIN_SCORE = 0.6
        validated = self._validated()
        with patch("enrich.classify_sentiment", return_value={"label": "positive", "score": 0.92}):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "positive")
        self.assertEqual(validated["sentiment"], "positive")
        self.assertEqual(validated["insight_json"]["overall_sentiment"], "positive")

    def test_low_confidence_classification_is_ignored(self):
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/sentiment-model"
        config.SENTIMENT_CLASSIFIER_MIN_SCORE = 0.6
        validated = self._validated()
        with patch("enrich.classify_sentiment", return_value={"label": "positive", "score": 0.3}):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "neutral")

    def test_non_neutral_llm_sentiment_is_never_overridden(self):
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/sentiment-model"
        validated = self._validated(sentiment="mixed")
        with patch("enrich.classify_sentiment", return_value={"label": "negative", "score": 0.99}) as mocked:
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        mocked.assert_not_called()
        self.assertEqual(validated["overall_sentiment"], "mixed")

    def test_classifier_returning_none_leaves_sentiment_untouched(self):
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/sentiment-model"
        validated = self._validated()
        with patch("enrich.classify_sentiment", return_value=None):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "neutral")


class EnrichArticleFallbackTests(unittest.TestCase):
    def test_llm_failure_returns_none_so_the_pipeline_can_fall_back(self):
        with patch("enrich.chat_completion", side_effect=RuntimeError("boom")):
            self.assertIsNone(enrich.enrich_article({"title": "t", "text": "x" * 300}))

    def test_invalid_json_from_the_llm_returns_none(self):
        with patch("enrich.chat_completion", return_value="not json"):
            self.assertIsNone(enrich.enrich_article({"title": "t", "text": "x" * 300}))


if __name__ == "__main__":
    unittest.main()
