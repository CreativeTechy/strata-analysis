import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from analysis import sentiment as analysis_sentiment


class ClassifyArticleSentimentTests(unittest.TestCase):
    def setUp(self):
        self._original_threshold = config.SENTIMENT_CONFIDENCE_THRESHOLD
        config.SENTIMENT_CONFIDENCE_THRESHOLD = 0.55

    def tearDown(self):
        config.SENTIMENT_CONFIDENCE_THRESHOLD = self._original_threshold

    def test_empty_text_defaults_to_neutral_low_confidence(self):
        result = analysis_sentiment.classify_article_sentiment("")
        self.assertEqual(result["label"], "neutral")
        self.assertTrue(result["low_confidence"])

    def test_confident_short_text_uses_classifier_label(self):
        with patch("analysis.sentiment.classify_sentiment", return_value={"label": "positive", "score": 0.9}):
            result = analysis_sentiment.classify_article_sentiment("great car")
        self.assertEqual(result["label"], "positive")
        self.assertFalse(result["low_confidence"])

    def test_low_confidence_downgrades_to_neutral_but_keeps_raw_label(self):
        with patch("analysis.sentiment.classify_sentiment", return_value={"label": "positive", "score": 0.3}):
            result = analysis_sentiment.classify_article_sentiment("great car")
        self.assertEqual(result["label"], "neutral")
        self.assertTrue(result["low_confidence"])
        self.assertEqual(result["raw_label"], "positive")

    def test_classifier_unavailable_defaults_to_neutral(self):
        with patch("analysis.sentiment.classify_sentiment", return_value=None):
            result = analysis_sentiment.classify_article_sentiment("great car")
        self.assertEqual(result["label"], "neutral")
        self.assertTrue(result["low_confidence"])

    def test_classifier_raising_defaults_to_neutral_without_crashing(self):
        with patch("analysis.sentiment.classify_sentiment", side_effect=RuntimeError("boom")):
            result = analysis_sentiment.classify_article_sentiment("great car")
        self.assertEqual(result["label"], "neutral")

    def test_long_text_is_chunked_and_aggregated(self):
        long_text = " ".join(f"word{i}" for i in range(3000))
        with patch("analysis.sentiment.classify_sentiment", return_value={"label": "negative", "score": 0.8}):
            result = analysis_sentiment.classify_article_sentiment(long_text)
        self.assertEqual(result["label"], "negative")
        self.assertFalse(result["low_confidence"])


if __name__ == "__main__":
    unittest.main()
