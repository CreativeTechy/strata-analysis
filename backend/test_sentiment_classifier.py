import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
import sentiment_classifier as sc


class ResolveDeviceTests(unittest.TestCase):
    def setUp(self):
        self._original = config.SENTIMENT_CLASSIFIER_DEVICE

    def tearDown(self):
        config.SENTIMENT_CLASSIFIER_DEVICE = self._original

    def test_cpu_maps_to_negative_one(self):
        config.SENTIMENT_CLASSIFIER_DEVICE = "cpu"
        self.assertEqual(sc._resolve_device(), -1)

    def test_unset_defaults_to_cpu(self):
        config.SENTIMENT_CLASSIFIER_DEVICE = ""
        self.assertEqual(sc._resolve_device(), -1)

    def test_cuda_without_index_defaults_to_device_zero(self):
        config.SENTIMENT_CLASSIFIER_DEVICE = "cuda"
        self.assertEqual(sc._resolve_device(), 0)

    def test_cuda_with_index_is_parsed(self):
        config.SENTIMENT_CLASSIFIER_DEVICE = "cuda:1"
        self.assertEqual(sc._resolve_device(), 1)


class ClassifySentimentTests(unittest.TestCase):
    def setUp(self):
        self._original_enabled = config.ENABLE_SENTIMENT_CLASSIFIER
        self._original_model = config.SENTIMENT_CLASSIFIER_MODEL
        sc._load_pipeline.cache_clear()

    def tearDown(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = self._original_enabled
        config.SENTIMENT_CLASSIFIER_MODEL = self._original_model
        sc._load_pipeline.cache_clear()

    def test_disabled_returns_none_without_loading_a_model(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = False
        with patch("sentiment_classifier._load_pipeline") as mocked:
            self.assertIsNone(sc.classify_sentiment("great product"))
        mocked.assert_not_called()

    def test_enabled_but_no_model_configured_returns_none(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        config.SENTIMENT_CLASSIFIER_MODEL = ""
        self.assertIsNone(sc.classify_sentiment("great product"))

    def test_empty_text_returns_none(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        self.assertIsNone(sc.classify_sentiment("   "))

    def test_successful_classification_is_normalized(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        fake_pipeline = lambda text: [{"label": "LABEL_2", "score": 0.87}]
        with patch("sentiment_classifier._load_pipeline", return_value=fake_pipeline):
            result = sc.classify_sentiment("I love this")
        self.assertEqual(result, {"label": "positive", "score": 0.87})

    def test_human_readable_labels_pass_through_case_insensitively(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        fake_pipeline = lambda text: [{"label": "NEGATIVE", "score": 0.7}]
        with patch("sentiment_classifier._load_pipeline", return_value=fake_pipeline):
            result = sc.classify_sentiment("terrible")
        self.assertEqual(result, {"label": "negative", "score": 0.7})

    def test_pipeline_unavailable_returns_none(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        with patch("sentiment_classifier._load_pipeline", return_value=None):
            self.assertIsNone(sc.classify_sentiment("I love this"))

    def test_inference_error_returns_none_instead_of_raising(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"

        def boom(text):
            raise RuntimeError("boom")

        with patch("sentiment_classifier._load_pipeline", return_value=boom):
            self.assertIsNone(sc.classify_sentiment("I love this"))

    def test_unrecognized_label_returns_none(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        fake_pipeline = lambda text: [{"label": "surprise", "score": 0.5}]
        with patch("sentiment_classifier._load_pipeline", return_value=fake_pipeline):
            self.assertIsNone(sc.classify_sentiment("huh"))

    def test_missing_transformers_package_is_handled_gracefully(self):
        config.ENABLE_SENTIMENT_CLASSIFIER = True
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        with patch.dict("sys.modules", {"transformers": None}):
            self.assertIsNone(sc.classify_sentiment("great product"))


if __name__ == "__main__":
    unittest.main()
