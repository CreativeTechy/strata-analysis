"""Unit tests for services/projects/project_name_translations.py: default
locale skips the LLM, cached names are reused, misses are translated in
bounded batches and cached per batch, and failures fall back to the
original name (and are not retried within the failure window)."""

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from services.projects import project_name_translations as pnt


def _fake_chat(**kwargs):
    names = json.loads(kwargs["messages"][1]["content"])["names"]
    return json.dumps({"names": [f"ar:{n}" for n in names]})


class LocalizeProjectNamesTests(unittest.TestCase):
    def setUp(self):
        pnt._failure_cache.clear()

    def test_default_locale_never_calls_the_llm(self):
        with patch.object(pnt, "chat_completion") as chat:
            result = pnt.localize_project_names([{"id": 1, "name": "Alpha"}], locale=config.DEFAULT_LOCALE)
        chat.assert_not_called()
        self.assertEqual(result[0]["display_name"], "Alpha")

    def test_cached_name_is_reused(self):
        with patch.object(pnt, "_load_cached", return_value={(1, "Alpha"): "ألفا"}), \
             patch.object(pnt, "chat_completion") as chat:
            result = pnt.localize_project_names([{"id": 1, "name": "Alpha"}], locale="ar")
        chat.assert_not_called()
        self.assertEqual(result[0]["display_name"], "ألفا")

    def test_rename_misses_cache(self):
        with patch.object(pnt, "_load_cached", return_value={(1, "Old"): "قديم"}), \
             patch.object(pnt, "_save_cached"), \
             patch.object(pnt, "chat_completion", side_effect=_fake_chat) as chat:
            result = pnt.localize_project_names([{"id": 1, "name": "New"}], locale="ar")
        chat.assert_called_once()
        self.assertEqual(result[0]["display_name"], "ar:New")

    def test_many_names_are_translated_in_bounded_batches(self):
        projects = [{"id": i, "name": f"P{i:03d}"} for i in range(45)]
        with patch.object(pnt, "_load_cached", return_value={}), \
             patch.object(pnt, "_save_cached") as save, \
             patch.object(pnt, "chat_completion", side_effect=_fake_chat) as chat:
            result = pnt.localize_project_names(projects, locale="ar")
        self.assertEqual(chat.call_count, 3)
        self.assertEqual(save.call_count, 3)
        self.assertTrue(all(r["display_name"] == f"ar:{r['name']}" for r in result))

    def test_failure_falls_back_and_is_not_retried_in_window(self):
        projects = [{"id": 1, "name": "Alpha"}]
        with patch.object(pnt, "_load_cached", return_value={}), \
             patch.object(pnt, "_save_cached"), \
             patch.object(pnt, "chat_completion", return_value=None) as chat:
            first = pnt.localize_project_names(projects, locale="ar")
            pnt.localize_project_names(projects, locale="ar")
        self.assertEqual(first[0]["display_name"], "Alpha")
        self.assertEqual(chat.call_count, 1)

    def test_wrong_length_response_falls_back(self):
        with patch.object(pnt, "_load_cached", return_value={}), \
             patch.object(pnt, "_save_cached") as save, \
             patch.object(pnt, "chat_completion", return_value=json.dumps({"names": []})):
            result = pnt.localize_project_names([{"id": 1, "name": "Alpha"}], locale="ar")
        save.assert_not_called()
        self.assertEqual(result[0]["display_name"], "Alpha")


if __name__ == "__main__":
    unittest.main()
