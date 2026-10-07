"""Unit tests for services/i18n/label_translation.py.

Covers: identity for the default locale, reusing cached labels, translating
only cache misses in batches, falling back to the original text when a label
can not be translated, resilience to a malformed batch, the per-project
provider-failure pause, and the request-body bounds in clean_labels().
"""

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from llm_client import LLMConnectionError
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
            result = label_translation.translate_labels(7, ["Middle East"], config.DEFAULT_LOCALE)
        self.assertEqual(result, {"Middle East": "Middle East"})
        mock_chat.assert_not_called()
        mock_load.assert_not_called()

    def test_translates_only_cache_misses_and_saves_them(self):
        with patch.object(label_translation, "_load_cached", return_value={"Middle East": "الشرق الأوسط"}), \
             patch.object(label_translation, "_save_cached") as mock_save, \
             patch.object(label_translation, "chat_completion", side_effect=_echo_arabic) as mock_chat:
            result = label_translation.translate_labels(7, ["Middle East", "small_business_owner"], "ar")
        self.assertEqual(result, {"Middle East": "الشرق الأوسط", "small_business_owner": "ar:small_business_owner"})
        self.assertEqual(mock_chat.call_count, 1)
        mock_save.assert_called_once_with(7, "ar", {"small_business_owner": "ar:small_business_owner"})

    def test_cache_is_read_for_the_requesting_project_only(self):
        with patch.object(label_translation, "_load_cached", return_value={}) as mock_load, \
             patch.object(label_translation, "_save_cached"), \
             patch.object(label_translation, "chat_completion", side_effect=_echo_arabic):
            label_translation.translate_labels(7, ["Gulf"], "ar")
        mock_load.assert_called_once_with(7, "ar", ["Gulf"])

    def test_splits_misses_into_batches(self):
        labels = [f"segment {i}" for i in range(label_translation.BATCH_SIZE + 5)]
        with patch.object(label_translation, "_load_cached", return_value={}), \
             patch.object(label_translation, "_save_cached"), \
             patch.object(label_translation, "chat_completion", side_effect=_echo_arabic) as mock_chat:
            result = label_translation.translate_labels(7, labels, "ar")
        self.assertEqual(mock_chat.call_count, 2)
        self.assertEqual(result["segment 0"], "ar:segment 0")

    def test_provider_failure_falls_back_to_source_text_and_pauses_retries(self):
        with patch.object(label_translation, "_load_cached", return_value={}), \
             patch.object(label_translation, "_save_cached") as mock_save, \
             patch.object(label_translation, "chat_completion", side_effect=LLMConnectionError("down")) as mock_chat:
            first = label_translation.translate_labels(7, ["Gulf"], "ar")
            second = label_translation.translate_labels(7, ["Gulf"], "ar")
        self.assertEqual(first, {"Gulf": "Gulf"})
        self.assertEqual(second, {"Gulf": "Gulf"})
        self.assertEqual(mock_chat.call_count, 1)
        mock_save.assert_not_called()

    def test_failure_pause_is_per_project(self):
        with patch.object(label_translation, "_load_cached", return_value={}), \
             patch.object(label_translation, "_save_cached"), \
             patch.object(label_translation, "chat_completion", side_effect=LLMConnectionError("down")) as mock_chat:
            label_translation.translate_labels(7, ["Gulf"], "ar")
            label_translation.translate_labels(8, ["Gulf"], "ar")
        self.assertEqual(mock_chat.call_count, 2)

    def test_wrong_length_response_keeps_source_without_pausing(self):
        with patch.object(label_translation, "_load_cached", return_value={}), \
             patch.object(label_translation, "_save_cached") as mock_save, \
             patch.object(label_translation, "chat_completion", return_value=json.dumps({"labels": []})):
            result = label_translation.translate_labels(7, ["Gulf"], "ar")
        self.assertEqual(result, {"Gulf": "Gulf"})
        mock_save.assert_not_called()
        self.assertEqual(label_translation._failure_cache, {})

    def test_malformed_batch_is_retried_in_halves_so_good_labels_still_translate(self):
        def flaky(messages, **_kwargs):
            labels = json.loads(messages[-1]["content"])["labels"]
            if len(labels) > 1 or labels == ["bad"]:
                return "not json"
            return json.dumps({"labels": [f"ar:{labels[0]}"]}, ensure_ascii=False)

        with patch.object(label_translation, "_load_cached", return_value={}), \
             patch.object(label_translation, "_save_cached") as mock_save, \
             patch.object(label_translation, "chat_completion", side_effect=flaky):
            result = label_translation.translate_labels(7, ["a", "bad", "c"], "ar")
        self.assertEqual(result, {"a": "ar:a", "bad": "bad", "c": "ar:c"})
        saved = {k: v for call in mock_save.call_args_list for k, v in call.args[2].items()}
        self.assertEqual(saved, {"a": "ar:a", "c": "ar:c"})
        self.assertEqual(label_translation._failure_cache, {})

    def test_output_budget_fits_the_largest_accepted_batch(self):
        labels = ["x" * label_translation.MAX_LABEL_LENGTH] * 4
        self.assertGreaterEqual(label_translation._output_budget(labels), 4 * label_translation.MAX_LABEL_LENGTH)

    def test_batches_respect_count_and_character_caps(self):
        batches = list(label_translation._batches(["y" * 900] * 5))
        self.assertTrue(all(len(batch) <= 2 for batch in batches))
        self.assertEqual(sum(len(batch) for batch in batches), 5)


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
