"""Unit tests for services/intelligence/idea_translation.py.

Covers: skipping the LLM call for the default locale or an empty ideas list,
reusing cached translations by idea text (not by project/period/run scope),
translating only the cache-miss ideas in one batched call, and falling back
to the original English text (without failing the whole request) when the
LLM call fails.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from services.intelligence import idea_translation

INTELLIGENCE = {
    "project_id": 10,
    "insights": {
        "frequent_ideas": [
            {"idea": "Users can't find dark mode", "type": "issue", "category": "ui", "frequency_estimate": 5},
            {"idea": "Battery life is great", "type": "praise", "category": "hardware", "frequency_estimate": 3},
        ],
    },
}


class LocalizeFrequentIdeasTests(unittest.TestCase):
    def setUp(self):
        idea_translation._failure_cache.clear()

    def test_default_locale_never_calls_the_llm(self):
        with patch("services.intelligence.idea_translation.chat_completion") as mock_chat, \
             patch.object(idea_translation, "_load_cached") as mock_load:
            result = idea_translation.localize_frequent_ideas(
                INTELLIGENCE, project_id=10, locale=config.DEFAULT_LOCALE,
            )
        self.assertEqual(result, INTELLIGENCE)
        mock_chat.assert_not_called()
        mock_load.assert_not_called()

    def test_empty_ideas_list_never_calls_the_llm(self):
        empty = {"project_id": 10, "insights": {"frequent_ideas": []}}
        with patch("services.intelligence.idea_translation.chat_completion") as mock_chat:
            result = idea_translation.localize_frequent_ideas(empty, project_id=10, locale="ar")
        self.assertEqual(result, empty)
        mock_chat.assert_not_called()

    def test_fully_cached_never_calls_the_llm(self):
        cached = {
            "Users can't find dark mode": "لا يمكن للمستخدمين العثور على الوضع الداكن",
            "Battery life is great": "عمر البطارية رائع",
        }
        with patch.object(idea_translation, "_load_cached", return_value=cached), \
             patch("services.intelligence.idea_translation.chat_completion") as mock_chat:
            result = idea_translation.localize_frequent_ideas(INTELLIGENCE, project_id=10, locale="ar")

        ideas = result["insights"]["frequent_ideas"]
        self.assertEqual(ideas[0]["idea"], "لا يمكن للمستخدمين العثور على الوضع الداكن")
        self.assertEqual(ideas[1]["idea"], "عمر البطارية رائع")
        # Non-text fields are untouched.
        self.assertEqual(ideas[0]["frequency_estimate"], 5)
        mock_chat.assert_not_called()

    def test_cache_miss_translates_only_the_missing_ideas_in_one_call(self):
        cached = {"Users can't find dark mode": "لا يمكن للمستخدمين العثور على الوضع الداكن"}
        with patch.object(idea_translation, "_load_cached", return_value=cached), \
             patch.object(idea_translation, "_save_cached") as mock_save, \
             patch.object(idea_translation, "_translate_ideas", return_value=["عمر البطارية رائع"]) as mock_translate:
            result = idea_translation.localize_frequent_ideas(INTELLIGENCE, project_id=10, locale="ar")

        mock_translate.assert_called_once_with(["Battery life is great"], "ar")
        mock_save.assert_called_once_with(10, "ar", {"Battery life is great": "عمر البطارية رائع"})
        ideas = result["insights"]["frequent_ideas"]
        self.assertEqual(ideas[0]["idea"], "لا يمكن للمستخدمين العثور على الوضع الداكن")
        self.assertEqual(ideas[1]["idea"], "عمر البطارية رائع")

    def test_translates_frequent_concerns_and_keeps_source_text(self):
        data = {"insights": {
            "frequent_ideas": [{"idea": "Battery life is great", "type": "praise"}],
            "frequent_concerns": [{"idea": "Users can't find dark mode", "type": "issue"}],
        }}
        cached = {
            "Battery life is great": "عمر البطارية رائع",
            "Users can't find dark mode": "لا يمكن للمستخدمين العثور على الوضع الداكن",
        }
        with patch.object(idea_translation, "_load_cached", return_value=cached),              patch("services.intelligence.idea_translation.chat_completion") as mock_chat:
            result = idea_translation.localize_frequent_ideas(data, project_id=10, locale="ar")

        concern = result["insights"]["frequent_concerns"][0]
        self.assertEqual(concern["idea"], "لا يمكن للمستخدمين العثور على الوضع الداكن")
        self.assertEqual(concern["source_text"], "Users can't find dark mode")
        self.assertEqual(result["insights"]["frequent_ideas"][0]["source_text"], "Battery life is great")
        mock_chat.assert_not_called()

    def test_llm_failure_falls_back_to_original_english_text(self):
        with patch.object(idea_translation, "_load_cached", return_value={}), \
             patch.object(idea_translation, "_save_cached") as mock_save, \
             patch.object(idea_translation, "_translate_ideas", side_effect=RuntimeError("model unreachable")):
            result = idea_translation.localize_frequent_ideas(INTELLIGENCE, project_id=10, locale="ar")

        ideas = result["insights"]["frequent_ideas"]
        self.assertEqual(ideas[0]["idea"], "Users can't find dark mode")
        self.assertEqual(ideas[1]["idea"], "Battery life is great")
        mock_save.assert_not_called()

    def test_recent_failure_short_circuits_without_calling_the_llm_again(self):
        with patch.object(idea_translation, "_load_cached", return_value={}), \
             patch.object(idea_translation, "_translate_ideas", side_effect=RuntimeError("model unreachable")) as mock_translate:
            idea_translation.localize_frequent_ideas(INTELLIGENCE, project_id=10, locale="ar")
            idea_translation.localize_frequent_ideas(INTELLIGENCE, project_id=10, locale="ar")

        mock_translate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
