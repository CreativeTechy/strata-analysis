"""Unit tests for services/intelligence/feedback_translation.py.

Covers: skipping the LLM call for the default locale or empty feedback
lists, reusing cached translations by feedback text (not by
project/period/run scope), translating only the cache-miss texts in one
batched call, and falling back to the original English text (without
failing the whole request) when the LLM call fails.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from services.intelligence import feedback_translation

INTELLIGENCE = {
    "project_id": 10,
    "insights": {
        "positive_feedback": [
            {"text": "Battery lasts all day", "count": 5},
        ],
        "negative_feedback": [
            {"text": "Shipping was slow", "count": 3},
        ],
    },
}


class LocalizeCategorizedFeedbackTests(unittest.TestCase):
    def setUp(self):
        feedback_translation._failure_cache.clear()

    def test_default_locale_never_calls_the_llm(self):
        with patch("services.intelligence.feedback_translation.chat_completion") as mock_chat, \
             patch.object(feedback_translation, "_load_cached") as mock_load:
            result = feedback_translation.localize_categorized_feedback(
                INTELLIGENCE, project_id=10, locale=config.DEFAULT_LOCALE,
            )
        self.assertEqual(result, INTELLIGENCE)
        mock_chat.assert_not_called()
        mock_load.assert_not_called()

    def test_empty_feedback_lists_never_call_the_llm(self):
        empty = {"project_id": 10, "insights": {"positive_feedback": [], "negative_feedback": []}}
        with patch("services.intelligence.feedback_translation.chat_completion") as mock_chat:
            result = feedback_translation.localize_categorized_feedback(empty, project_id=10, locale="ar")
        self.assertEqual(result, empty)
        mock_chat.assert_not_called()

    def test_fully_cached_never_calls_the_llm(self):
        cached = {
            "Battery lasts all day": "البطارية تدوم طوال اليوم",
            "Shipping was slow": "كان الشحن بطيئاً",
        }
        with patch.object(feedback_translation, "_load_cached", return_value=cached), \
             patch("services.intelligence.feedback_translation.chat_completion") as mock_chat:
            result = feedback_translation.localize_categorized_feedback(INTELLIGENCE, project_id=10, locale="ar")

        self.assertEqual(result["insights"]["positive_feedback"][0]["text"], "البطارية تدوم طوال اليوم")
        self.assertEqual(result["insights"]["negative_feedback"][0]["text"], "كان الشحن بطيئاً")
        # Non-text fields are untouched.
        self.assertEqual(result["insights"]["positive_feedback"][0]["count"], 5)
        mock_chat.assert_not_called()

    def test_cache_miss_translates_only_the_missing_texts_in_one_call(self):
        cached = {"Battery lasts all day": "البطارية تدوم طوال اليوم"}
        with patch.object(feedback_translation, "_load_cached", return_value=cached), \
             patch.object(feedback_translation, "_save_cached") as mock_save, \
             patch.object(feedback_translation, "_translate_texts", return_value=["كان الشحن بطيئاً"]) as mock_translate:
            result = feedback_translation.localize_categorized_feedback(INTELLIGENCE, project_id=10, locale="ar")

        mock_translate.assert_called_once_with(["Shipping was slow"], "ar")
        mock_save.assert_called_once_with(10, "ar", {"Shipping was slow": "كان الشحن بطيئاً"})
        self.assertEqual(result["insights"]["positive_feedback"][0]["text"], "البطارية تدوم طوال اليوم")
        self.assertEqual(result["insights"]["negative_feedback"][0]["text"], "كان الشحن بطيئاً")

    def test_llm_failure_falls_back_to_original_english_text(self):
        with patch.object(feedback_translation, "_load_cached", return_value={}), \
             patch.object(feedback_translation, "_save_cached") as mock_save, \
             patch.object(feedback_translation, "_translate_texts", side_effect=RuntimeError("model unreachable")):
            result = feedback_translation.localize_categorized_feedback(INTELLIGENCE, project_id=10, locale="ar")

        self.assertEqual(result["insights"]["positive_feedback"][0]["text"], "Battery lasts all day")
        self.assertEqual(result["insights"]["negative_feedback"][0]["text"], "Shipping was slow")
        mock_save.assert_not_called()

    def test_cache_read_failure_still_translates_instead_of_crashing(self):
        # e.g. project_feedback_translations doesn't exist yet on a database
        # that hasn't picked up migration 0047 - must not 500 the whole
        # /intelligence request, and must still attempt the translation.
        with patch.object(feedback_translation, "_load_cached", side_effect=RuntimeError("relation does not exist")), \
             patch.object(feedback_translation, "_save_cached") as mock_save, \
             patch.object(feedback_translation, "_translate_texts",
                           return_value=["البطارية تدوم طوال اليوم", "كان الشحن بطيئاً"]) as mock_translate:
            result = feedback_translation.localize_categorized_feedback(INTELLIGENCE, project_id=10, locale="ar")

        mock_translate.assert_called_once_with(["Battery lasts all day", "Shipping was slow"], "ar")
        self.assertEqual(result["insights"]["positive_feedback"][0]["text"], "البطارية تدوم طوال اليوم")
        self.assertEqual(result["insights"]["negative_feedback"][0]["text"], "كان الشحن بطيئاً")
        mock_save.assert_called_once()

    def test_cache_write_failure_still_returns_the_translation(self):
        with patch.object(feedback_translation, "_load_cached", return_value={}), \
             patch.object(feedback_translation, "_save_cached", side_effect=RuntimeError("relation does not exist")), \
             patch.object(feedback_translation, "_translate_texts",
                           return_value=["البطارية تدوم طوال اليوم", "كان الشحن بطيئاً"]):
            result = feedback_translation.localize_categorized_feedback(INTELLIGENCE, project_id=10, locale="ar")

        self.assertEqual(result["insights"]["positive_feedback"][0]["text"], "البطارية تدوم طوال اليوم")
        self.assertEqual(result["insights"]["negative_feedback"][0]["text"], "كان الشحن بطيئاً")

    def test_recent_failure_short_circuits_without_calling_the_llm_again(self):
        with patch.object(feedback_translation, "_load_cached", return_value={}), \
             patch.object(feedback_translation, "_translate_texts", side_effect=RuntimeError("model unreachable")) as mock_translate:
            feedback_translation.localize_categorized_feedback(INTELLIGENCE, project_id=10, locale="ar")
            feedback_translation.localize_categorized_feedback(INTELLIGENCE, project_id=10, locale="ar")

        mock_translate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
