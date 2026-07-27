import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import enrich


class NormalizeSentimentTests(unittest.TestCase):
    """_normalize_sentiment() is still used for per-item fields (people_opinions,
    frequent_ideas/feedback entries) - it is no longer used for the article-level
    overall_sentiment/sentiment, which come solely from the classifier."""

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
        }
        payload.update(overrides)
        return payload

    def test_missing_summary_is_treated_as_invalid(self):
        self.assertIsNone(enrich._validate_enrichment({"overall_sentiment": "positive"}))

    def test_non_dict_payload_is_invalid(self):
        self.assertIsNone(enrich._validate_enrichment("not a dict"))

    def test_llm_sentiment_is_ignored_regardless_of_value(self):
        """_validate_enrichment() never reads overall_sentiment/sentiment from
        the LLM payload - it always sets a neutral placeholder that
        _apply_sentiment_classifier() overwrites afterward."""
        for llm_value in ("positive", "negative", "mixed", "anything at all", None):
            validated = enrich._validate_enrichment(self._payload(overall_sentiment=llm_value))
            self.assertEqual(validated["overall_sentiment"], "neutral")
            self.assertEqual(validated["sentiment"], "neutral")
            self.assertEqual(validated["insight_json"]["overall_sentiment"], "neutral")

    def test_output_shape_is_unchanged(self):
        validated = enrich._validate_enrichment(self._payload())
        self.assertEqual(set(validated.keys()), set(enrich.DEFAULT_ENRICHMENT.keys()))


class SentimentClassifierIntegrationTests(unittest.TestCase):
    """Covers _apply_sentiment_classifier, the sole source of
    overall_sentiment/sentiment - it always runs and always wins over
    whatever the LLM produced."""

    def _validated(self):
        return dict(enrich._validate_enrichment({
            "summary": "A calm, factual write-up.",
        }))

    def test_confident_classification_sets_sentiment(self):
        validated = self._validated()
        with patch("enrich.classify_sentiment", return_value={"label": "positive", "score": 0.92}):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "positive")
        self.assertEqual(validated["sentiment"], "positive")
        self.assertEqual(validated["insight_json"]["overall_sentiment"], "positive")

    def test_low_confidence_classification_is_still_used_verbatim(self):
        """There is no LLM sentiment to fall back to, so even a low-confidence
        classifier label is used as-is - the classifier is the only source."""
        validated = self._validated()
        with patch("enrich.classify_sentiment", return_value={"label": "positive", "score": 0.3}):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "positive")

    def test_classifier_returning_none_defaults_to_neutral(self):
        validated = self._validated()
        with patch("enrich.classify_sentiment", return_value=None):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "neutral")
        self.assertEqual(validated["sentiment"], "neutral")
        self.assertEqual(validated["insight_json"]["overall_sentiment"], "neutral")

    def test_classifier_raising_defaults_to_neutral_without_crashing(self):
        validated = self._validated()
        with patch("enrich.classify_sentiment", side_effect=RuntimeError("boom")):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "neutral")

    def test_unrecognized_label_defaults_to_neutral(self):
        validated = self._validated()
        with patch("enrich.classify_sentiment", return_value={"label": "surprised", "score": 0.9}):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "neutral")

    def test_llm_sentiment_already_on_validated_is_overwritten(self):
        """Simulates a validated payload that somehow still carries an LLM
        sentiment - the classifier must replace it, never defer to it."""
        validated = self._validated()
        validated["overall_sentiment"] = "mixed"
        validated["sentiment"] = "mixed"
        validated["insight_json"]["overall_sentiment"] = "mixed"
        with patch("enrich.classify_sentiment", return_value={"label": "negative", "score": 0.8}):
            enrich._apply_sentiment_classifier(validated, title="t", text="body")
        self.assertEqual(validated["overall_sentiment"], "negative")
        self.assertEqual(validated["sentiment"], "negative")
        self.assertEqual(validated["insight_json"]["overall_sentiment"], "negative")


class EnrichArticleFallbackTests(unittest.TestCase):
    def test_llm_failure_returns_none_so_the_pipeline_can_fall_back(self):
        with patch("enrich.chat_completion", side_effect=RuntimeError("boom")):
            self.assertIsNone(enrich.enrich_article({"title": "t", "text": "x" * 300}))

    def test_invalid_json_from_the_llm_returns_none(self):
        with patch("enrich.chat_completion", return_value="not json"):
            self.assertIsNone(enrich.enrich_article({"title": "t", "text": "x" * 300}))


class EnrichArticleSentimentTests(unittest.TestCase):
    """End-to-end: enrich_article() with the LLM and embeddings mocked out.
    overall_sentiment/sentiment must always come from the classifier, and
    every other field must stay exactly what the LLM produced."""

    LLM_JSON = json.dumps({
        "summary": "A glowing review of the new model.",
        "topic": "new model launch",
        "article_category": "review",
        "overall_sentiment": "mixed",
        "writer_tone": "positive",
        "article_tone": "positive",
        "positive_feedback": ["great range"],
    })

    def setUp(self):
        self._patchers = [
            patch("enrich.chat_completion", return_value=self.LLM_JSON),
            patch("enrich.get_embedding", return_value={}),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()

    def test_classifier_sentiment_replaces_the_llm_sentiment(self):
        with patch("enrich.classify_sentiment", return_value={"label": "positive", "score": 0.95}):
            result = enrich.enrich_article({"title": "t", "text": "x" * 300})
        self.assertEqual(result["overall_sentiment"], "positive")
        self.assertEqual(result["sentiment"], "positive")
        self.assertEqual(result["insight_json"]["overall_sentiment"], "positive")
        # Everything else stays exactly what the LLM produced - the LLM's
        # "mixed" sentiment guess is nowhere in the output.
        self.assertEqual(result["topic"], "new model launch")
        self.assertEqual(result["article_category"], "review")
        self.assertEqual(result["writer_tone"], "positive")
        self.assertEqual(result["positive_feedback"], ["great range"])

    def test_classifier_unavailable_defaults_to_neutral_not_the_llm_sentiment(self):
        with patch("enrich.classify_sentiment", return_value=None):
            result = enrich.enrich_article({"title": "t", "text": "x" * 300})
        self.assertIsNotNone(result)
        self.assertEqual(result["overall_sentiment"], "neutral")
        self.assertEqual(result["sentiment"], "neutral")
        # Other fields are unaffected by the classifier's fallback.
        self.assertEqual(result["topic"], "new model launch")
        self.assertEqual(result["writer_tone"], "positive")


if __name__ == "__main__":
    unittest.main()
