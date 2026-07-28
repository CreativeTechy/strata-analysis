import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from analysis import language


class DetectLanguageTests(unittest.TestCase):
    def setUp(self):
        self._original_model = config.LANGUAGE_DETECTION_MODEL
        self._original_threshold = config.LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD
        config.LANGUAGE_DETECTION_MODEL = "fake/model"
        config.LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD = 0.5
        language._load_pipeline.cache_clear()

    def tearDown(self):
        config.LANGUAGE_DETECTION_MODEL = self._original_model
        config.LANGUAGE_DETECTION_CONFIDENCE_THRESHOLD = self._original_threshold
        language._load_pipeline.cache_clear()

    def test_empty_text_returns_none_language(self):
        result = language.detect_language("")
        self.assertIsNone(result["language"])
        self.assertTrue(result["low_confidence"])

    def test_confident_detection_is_used(self):
        fake_pipeline = lambda text: [{"label": "en", "score": 0.97}]
        with patch("analysis.language._get_pipeline", return_value=fake_pipeline):
            result = language.detect_language("hello world")
        self.assertEqual(result["language"], "en")
        self.assertFalse(result["low_confidence"])

    def test_low_confidence_keeps_the_label_but_flags_it(self):
        fake_pipeline = lambda text: [{"label": "fr", "score": 0.2}]
        with patch("analysis.language._get_pipeline", return_value=fake_pipeline):
            result = language.detect_language("bonjour")
        self.assertEqual(result["language"], "fr")
        self.assertTrue(result["low_confidence"])

    def test_no_model_configured_returns_none_language(self):
        config.LANGUAGE_DETECTION_MODEL = ""
        result = language.detect_language("hello")
        self.assertIsNone(result["language"])
        self.assertTrue(result["low_confidence"])

    def test_pipeline_unavailable_returns_none_language(self):
        with patch("analysis.language._get_pipeline", return_value=None):
            result = language.detect_language("hello")
        self.assertIsNone(result["language"])

    def test_inference_error_returns_none_language_without_crashing(self):
        def boom(text):
            raise RuntimeError("boom")

        with patch("analysis.language._get_pipeline", return_value=boom):
            result = language.detect_language("hello")
        self.assertIsNone(result["language"])
        self.assertTrue(result["low_confidence"])


if __name__ == "__main__":
    unittest.main()
