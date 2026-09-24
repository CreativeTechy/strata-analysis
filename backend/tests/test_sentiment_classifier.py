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
        self._original_model = config.SENTIMENT_CLASSIFIER_MODEL
        sc._load_pipeline.cache_clear()

    def tearDown(self):
        config.SENTIMENT_CLASSIFIER_MODEL = self._original_model
        sc._load_pipeline.cache_clear()

    def test_no_model_configured_returns_none(self):
        config.SENTIMENT_CLASSIFIER_MODEL = ""
        self.assertIsNone(sc.classify_sentiment("great product"))

    def test_empty_text_returns_none(self):
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        self.assertIsNone(sc.classify_sentiment("   "))

    def test_successful_classification_is_normalized(self):
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        fake_pipeline = lambda text, **kwargs: [{"label": "LABEL_2", "score": 0.87}]
        with patch("sentiment_classifier._load_pipeline", return_value=fake_pipeline):
            result = sc.classify_sentiment("I love this")
        self.assertEqual(result, {"label": "positive", "score": 0.87})

    def test_human_readable_labels_pass_through_case_insensitively(self):
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        fake_pipeline = lambda text, **kwargs: [{"label": "NEGATIVE", "score": 0.7}]
        with patch("sentiment_classifier._load_pipeline", return_value=fake_pipeline):
            result = sc.classify_sentiment("terrible")
        self.assertEqual(result, {"label": "negative", "score": 0.7})

    def test_pipeline_unavailable_returns_none(self):
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        with patch("sentiment_classifier._load_pipeline", return_value=None):
            self.assertIsNone(sc.classify_sentiment("I love this"))

    def test_inference_error_returns_none_instead_of_raising(self):
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"

        def boom(text, **kwargs):
            raise RuntimeError("boom")

        with patch("sentiment_classifier._load_pipeline", return_value=boom):
            self.assertIsNone(sc.classify_sentiment("I love this"))

    def test_unrecognized_label_returns_none(self):
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        fake_pipeline = lambda text, **kwargs: [{"label": "surprise", "score": 0.5}]
        with patch("sentiment_classifier._load_pipeline", return_value=fake_pipeline):
            self.assertIsNone(sc.classify_sentiment("huh"))

    def test_missing_transformers_package_is_handled_gracefully(self):
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        with patch.dict("sys.modules", {"transformers": None}):
            self.assertIsNone(sc.classify_sentiment("great product"))


class ClassifySentimentHfApiTests(unittest.TestCase):
    def setUp(self):
        self._original_model = config.SENTIMENT_CLASSIFIER_MODEL
        self._original_provider = config.SENTIMENT_CLASSIFIER_PROVIDER
        config.SENTIMENT_CLASSIFIER_MODEL = "fake/model"
        config.SENTIMENT_CLASSIFIER_PROVIDER = "hf_api"

    def tearDown(self):
        config.SENTIMENT_CLASSIFIER_MODEL = self._original_model
        config.SENTIMENT_CLASSIFIER_PROVIDER = self._original_provider

    def test_successful_classification_is_normalized(self):
        with patch("hf_inference_client.classify_text", return_value=[{"label": "LABEL_2", "score": 0.87}]):
            result = sc.classify_sentiment("I love this")
        self.assertEqual(result, {"label": "positive", "score": 0.87})

    def test_picks_highest_scoring_label_when_multiple_are_returned(self):
        fake_results = [
            {"label": "negative", "score": 0.1},
            {"label": "positive", "score": 0.75},
            {"label": "neutral", "score": 0.15},
        ]
        with patch("hf_inference_client.classify_text", return_value=fake_results):
            result = sc.classify_sentiment("I love this")
        self.assertEqual(result, {"label": "positive", "score": 0.75})

    def test_empty_result_list_returns_none(self):
        with patch("hf_inference_client.classify_text", return_value=[]):
            self.assertIsNone(sc.classify_sentiment("I love this"))

    def test_api_error_propagates_instead_of_returning_none(self):
        """An HF Inference API failure (bad token, quota, rate limit,
        outage...) means every remaining article would fail the same way -
        it must propagate instead of quietly downgrading to "no result", so
        the pipeline can treat it as fatal and stop (see
        services/articles/analysis_defaults.py's FATAL_ANALYSIS_ERRORS)."""
        from hf_inference_client import HFInferenceError

        with patch("hf_inference_client.classify_text", side_effect=HFInferenceError("boom")):
            with self.assertRaises(HFInferenceError):
                sc.classify_sentiment("I love this")

    def test_unrecognized_label_returns_none(self):
        with patch("hf_inference_client.classify_text", return_value=[{"label": "surprise", "score": 0.9}]):
            self.assertIsNone(sc.classify_sentiment("huh"))

    def test_400_error_retries_once_with_shorter_text_and_succeeds(self):
        from hf_inference_client import HFInferenceError

        long_text = "x" * 500
        calls = []

        def fake_classify_text(model_name, text):
            calls.append(text)
            if len(calls) == 1:
                raise HFInferenceError("too long", status=400)
            return [{"label": "LABEL_2", "score": 0.6}]

        with patch("hf_inference_client.classify_text", side_effect=fake_classify_text):
            result = sc.classify_sentiment(long_text)

        self.assertEqual(result, {"label": "positive", "score": 0.6})
        self.assertEqual(len(calls), 2)
        self.assertLessEqual(len(calls[1].encode("utf-8")), sc._HF_API_RETRY_MAX_BYTES)

    def test_400_error_retry_stays_within_byte_budget_for_multibyte_text(self):
        """A character-count cap isn't a token-count cap: 500 Chinese
        characters are 1500 UTF-8 bytes, and a byte-level BPE tokenizer can
        need close to one token per byte for a script it wasn't trained on.
        The retried payload must be capped by bytes, not characters, so it
        reliably fits the model's token limit."""
        from hf_inference_client import HFInferenceError

        long_text = "中" * 500  # 500 CJK characters = 1500 UTF-8 bytes
        calls = []

        def fake_classify_text(model_name, text):
            calls.append(text)
            if len(calls) == 1:
                raise HFInferenceError("too long", status=400)
            return [{"label": "LABEL_2", "score": 0.6}]

        with patch("hf_inference_client.classify_text", side_effect=fake_classify_text):
            result = sc.classify_sentiment(long_text)

        self.assertEqual(result, {"label": "positive", "score": 0.6})
        self.assertEqual(len(calls), 2)
        self.assertLessEqual(len(calls[1].encode("utf-8")), sc._HF_API_RETRY_MAX_BYTES)
        # Every character in the retried slice should still be whole, not a
        # truncated multi-byte sequence.
        self.assertTrue(set(calls[1]) <= {"中"})

    def test_400_error_on_already_short_text_propagates(self):
        from hf_inference_client import HFInferenceError

        with patch("hf_inference_client.classify_text", side_effect=HFInferenceError("too long", status=400)):
            with self.assertRaises(HFInferenceError):
                sc.classify_sentiment("short")

    def test_non_400_error_does_not_retry(self):
        from hf_inference_client import HFInferenceError

        calls = []

        def fake_classify_text(model_name, text):
            calls.append(text)
            raise HFInferenceError("rate limited", status=429)

        with patch("hf_inference_client.classify_text", side_effect=fake_classify_text):
            with self.assertRaises(HFInferenceError):
                sc.classify_sentiment("x" * 500)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
