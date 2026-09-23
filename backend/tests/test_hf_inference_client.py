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

    def test_400_error_carries_status_on_the_wrapped_exception(self):
        mock_client = MagicMock()
        mock_client.text_classification.side_effect = HfHubHTTPError(
            "400 error", response=MagicMock(status_code=400)
        )
        with patch("hf_inference_client.InferenceClient", return_value=mock_client):
            with self.assertRaises(hf.HFInferenceError) as ctx:
                hf.classify_text("fake/model", "great")
        self.assertEqual(ctx.exception.status, 400)

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


class ByteBudgetTruncationTests(unittest.TestCase):
    def test_truncate_returns_text_unchanged_when_within_budget(self):
        self.assertEqual(hf.truncate_to_byte_budget("hello", 480), "hello")

    def test_truncate_caps_ascii_text_by_byte_count(self):
        text = "x" * 500
        truncated = hf.truncate_to_byte_budget(text, 480)
        self.assertEqual(len(truncated.encode("utf-8")), 480)

    def test_truncate_never_splits_a_multibyte_character(self):
        # Each "中" is 3 UTF-8 bytes; a 481-byte budget doesn't land on a
        # character boundary, forcing a partial trailing character.
        text = "中" * 200  # 600 bytes
        truncated = hf.truncate_to_byte_budget(text, 481)
        self.assertLessEqual(len(truncated.encode("utf-8")), 481)
        # No partial character leaked through as a decoding artifact.
        self.assertTrue(set(truncated) <= {"中"})

    def test_split_into_pieces_preserves_all_content(self):
        text = "x" * 900
        pieces = hf.split_into_byte_budget_pieces(text, 400)
        self.assertEqual("".join(pieces), text)
        for piece in pieces[:-1]:
            self.assertEqual(len(piece.encode("utf-8")), 400)
        self.assertLessEqual(len(pieces[-1].encode("utf-8")), 400)

    def test_split_into_pieces_preserves_multibyte_content_without_splitting_characters(self):
        text = "中" * 300  # 900 UTF-8 bytes
        pieces = hf.split_into_byte_budget_pieces(text, 400)
        self.assertEqual("".join(pieces), text)
        for piece in pieces:
            self.assertLessEqual(len(piece.encode("utf-8")), 400)
            self.assertTrue(set(piece) <= {"中"})

    def test_split_of_text_within_budget_returns_single_piece(self):
        self.assertEqual(hf.split_into_byte_budget_pieces("hello", 480), ["hello"])


if __name__ == "__main__":
    unittest.main()
