import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
import hf_inference_client as hf
from huggingface_hub.errors import HfHubHTTPError, InferenceTimeoutError


def _label_score(label, score):
    obj = MagicMock()
    obj.label = label
    obj.score = score
    return obj


class HfInferenceClientTests(unittest.TestCase):
    def setUp(self):
        self._original_token = config.HF_API_TOKEN
        self._original_base_url = config.HF_API_BASE_URL
        config.HF_API_TOKEN = "test-token"
        config.HF_API_BASE_URL = ""

    def tearDown(self):
        config.HF_API_TOKEN = self._original_token
        config.HF_API_BASE_URL = self._original_base_url

    def test_missing_token_raises_before_creating_a_client(self):
        config.HF_API_TOKEN = ""
        with patch("hf_inference_client.InferenceClient") as mock_client_cls:
            with self.assertRaises(hf.HFInferenceError):
                hf.classify_text("fake/model", "hello")
        mock_client_cls.assert_not_called()

    def test_classify_text_returns_label_score_dicts(self):
        mock_client = MagicMock()
        mock_client.text_classification.return_value = [_label_score("POSITIVE", 0.9)]
        with patch("hf_inference_client.InferenceClient", return_value=mock_client):
            result = hf.classify_text("fake/model", "great")
        self.assertEqual(result, [{"label": "POSITIVE", "score": 0.9}])
        mock_client.text_classification.assert_called_once_with("great", model="fake/model")

    def test_classify_zero_shot_returns_labels_and_scores(self):
        mock_client = MagicMock()
        mock_client.zero_shot_classification.return_value = [
            _label_score("news", 0.7),
            _label_score("review", 0.2),
        ]
        with patch("hf_inference_client.InferenceClient", return_value=mock_client):
            result = hf.classify_zero_shot("fake/model", "text", ["news", "review"], "This is {}.")
        self.assertEqual(result, {"labels": ["news", "review"], "scores": [0.7, 0.2]})

    def test_classify_zero_shot_empty_response_raises(self):
        mock_client = MagicMock()
        mock_client.zero_shot_classification.return_value = []
        with patch("hf_inference_client.InferenceClient", return_value=mock_client):
            with self.assertRaises(hf.HFInferenceError):
                hf.classify_zero_shot("fake/model", "text", ["news"], "This is {}.")

    def test_http_error_is_wrapped_as_hf_inference_error(self):
        mock_client = MagicMock()
        mock_client.text_classification.side_effect = HfHubHTTPError("500 error", response=MagicMock())
        with patch("hf_inference_client.InferenceClient", return_value=mock_client):
            with self.assertRaises(hf.HFInferenceError):
                hf.classify_text("fake/model", "great")

    def test_timeout_error_is_wrapped_as_hf_inference_error(self):
        mock_client = MagicMock()
        mock_client.text_classification.side_effect = InferenceTimeoutError("timed out")
        with patch("hf_inference_client.InferenceClient", return_value=mock_client):
            with self.assertRaises(hf.HFInferenceError):
                hf.classify_text("fake/model", "great")

    def test_uses_hf_inference_provider_routing_by_default(self):
        with patch("hf_inference_client.InferenceClient") as mock_client_cls:
            mock_client_cls.return_value.text_classification.return_value = [_label_score("POSITIVE", 0.9)]
            hf.classify_text("fake/model", "great")
        _, kwargs = mock_client_cls.call_args
        self.assertEqual(kwargs["provider"], "hf-inference")
        self.assertNotIn("base_url", kwargs)
        self.assertEqual(kwargs["token"], "test-token")

    def test_dedicated_base_url_overrides_provider_routing(self):
        config.HF_API_BASE_URL = "https://my-endpoint.example.com"
        with patch("hf_inference_client.InferenceClient") as mock_client_cls:
            mock_client_cls.return_value.text_classification.return_value = [_label_score("POSITIVE", 0.9)]
            hf.classify_text("fake/model", "great")
        _, kwargs = mock_client_cls.call_args
        self.assertEqual(kwargs["base_url"], "https://my-endpoint.example.com")
        self.assertNotIn("provider", kwargs)


if __name__ == "__main__":
    unittest.main()
