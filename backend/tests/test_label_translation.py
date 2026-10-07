"""Unit tests for services/i18n/label_translation.py.

Covers: identity for the default locale, reusing cached labels, translating
only cache misses in batches, falling back to the original text when the
LLM fails, and the request-body bounds in clean_labels().
"""

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from services.i18n import label_translation


def _echo_arabic(messages, **_kwargs):
    labels = json.loads(messages[-1]["content"])["labels"]
    return json.dumps({"labels": [f"ar:{label}" for label in labels]}, ensure_ascii=False)


class TranslateLabelsTests(unittest.TestCase):
    def setUp(self):
        label_translation._failure_cache.clear()

    def test_default_locale_is_identity_without_llm_or_db(self):
        with patch.object(label_translation, "chat_completion") as mock_chat, \
             patch.object(label_translation, "_load_cached") as mock_load:
            result = label_translation.translate_labels(["Middle East"], config.DEFAULT_LOCALE)
        self.assertEqual(result, {"Middle East": "Middle East"})
        mock_chat.assert_not_called()
        mock_load.assert_not_called()

    def test_translates_only_cache_misses_and_saves_them(self):
        with patch.object(label_translation, "_load_cached", return_value={"Middle East": "الشرق الأوسط"}), \
             patch.object(label_translation, "_save_cached") as mock_save, \
             patch.object(label_translation, "chat_completion", side_effect=_echo_arabic) as mock_chat:
            result = label_translation.translate_labels(["Middle East", "small_business_owner"], "ar")
        self.assertEqual(result, {"Middle East": "الشرق الأوسط", "small_business_owner": "ar:small_business_owner"})
        self.assertEqual(mock_chat.call_count, 1)
        mock_save.assert_called_once_with("ar", {"small_business_owner": "ar:small_business_owner"})

    def test_splits_misses_into_batches(self):
        labels = [f"segment {i}" for i in range(label_translation.BATCH_SIZE + 5)]
        with patch.object(label_translation, "_load_cached", return_value={}), \
             patch.object(label_translation, "_save_cached"), \
             patch.object(label_translation, "chat_completion", side_effect=_echo_arabic) as mock_chat:
            result = label_translation.translate_labels(labels, "ar")
        self.assertEqual(mock_chat.call_count, 2)
        self.assertEqual(result["segment 0"], "ar:segment 0")

    def test_llm_failure_falls_back_to_source_text_and_pauses_retries(self):
        with patch.object(label_translation, "_load_cached", return_value={}), \
             patch.object(label_translation, "_save_cached") as mock_save, \
             patch.object(label_translation, "chat_completion", side_effect=RuntimeError("down")) as mock_chat:
            first = label_translation.translate_labels(["Gulf"], "ar")
            second = label_translation.translate_labels(["Gulf"], "ar")
        self.assertEqual(first, {"Gulf": "Gulf"})
        self.assertEqual(second, {"Gulf": "Gulf"})
        self.assertEqual(mock_chat.call_count, 1)
        mock_save.assert_not_called()

    def test_wrong_length_response_is_a_failure(self):
        with patch.object(label_translation, "_load_cached", return_value={}), \
             patch.object(label_translation, "_save_cached") as mock_save, \
             patch.object(label_translation, "chat_completion", return_value=json.dumps({"labels": []})):
            result = label_translation.translate_labels(["Gulf"], "ar")
        self.assertEqual(result, {"Gulf": "Gulf"})
        mock_save.assert_not_called()


class CleanLabelsTests(unittest.TestCase):
    def test_dedupes_strips_and_drops_blank_or_oversized(self):
        too_long = "x" * (label_translation.MAX_LABEL_LENGTH + 1)
        self.assertEqual(label_translation.clean_labels([" Gulf ", "Gulf", "", too_long, "Retired"]), ["Gulf", "Retired"])

    def test_caps_the_number_of_labels(self):
        values = [f"v{i}" for i in range(label_translation.MAX_LABELS_PER_REQUEST + 10)]
        self.assertEqual(len(label_translation.clean_labels(values)), label_translation.MAX_LABELS_PER_REQUEST)

    def test_rejects_non_string_values(self):
        with self.assertRaises(ValueError):
            label_translation.clean_labels(["ok", 3])
        with self.assertRaises(ValueError):
            label_translation.clean_labels("Gulf")


if __name__ == "__main__":
    unittest.main()
