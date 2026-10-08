"""Unit tests for services/competitors/competitor_name_translations.py:
default locale skips the LLM, cached names are reused, misses are rendered in
bounded batches and cached per batch, a provider failure falls back to the
original name (and is not retried within the failure window), and a mangled
batch keeps its names without pausing the rest."""

import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from llm_client import LLMConnectionError, LLMTimeoutError
from services.competitors import competitor_name_translations as cnt


def _fake_chat(**kwargs):
    names = json.loads(kwargs["messages"][1]["content"])["names"]
    return json.dumps({"names": [f"ar:{n}" for n in names]})


class TranslateCompetitorNamesTests(unittest.TestCase):
    def setUp(self):
        cnt._failure_cache.clear()

    def test_default_locale_never_calls_the_llm(self):
        with patch.object(cnt, "chat_completion") as chat, patch.object(cnt, "_load_cached") as load:
            result = cnt.localize_competitors(1, [{"id": 7, "name": "Acme"}], locale=config.DEFAULT_LOCALE)
        chat.assert_not_called()
        load.assert_not_called()
        self.assertEqual(result[0]["display_name"], "Acme")

    def test_cached_name_is_reused_and_only_misses_are_translated(self):
        with patch.object(cnt, "_load_cached", return_value={"Acme": "أكمي"}), \
             patch.object(cnt, "_save_cached") as save, \
             patch.object(cnt, "chat_completion", side_effect=_fake_chat) as chat:
            result = cnt.localize_competitors(
                1, [{"id": 7, "name": "Acme"}, {"id": 8, "name": " Globex "}], locale="ar",
            )
        chat.assert_called_once()
        self.assertEqual(json.loads(chat.call_args.kwargs["messages"][1]["content"]), {"names": ["Globex"]})
        save.assert_called_once_with(1, "ar", {"Globex": "ar:Globex"})
        self.assertEqual([r["display_name"] for r in result], ["أكمي", "ar:Globex"])
        # The canonical name is never rewritten.
        self.assertEqual([r["name"] for r in result], ["Acme", " Globex "])

    def test_many_names_are_translated_in_bounded_batches(self):
        names = [f"C{i:03d}" for i in range(45)]
        with patch.object(cnt, "_load_cached", return_value={}), \
             patch.object(cnt, "_save_cached") as save, \
             patch.object(cnt, "chat_completion", side_effect=_fake_chat) as chat:
            result = cnt.translate_competitor_names(1, names, locale="ar")
        self.assertEqual(chat.call_count, 3)
        self.assertEqual(save.call_count, 3)
        self.assertEqual(result, {name: f"ar:{name}" for name in names})

    def test_provider_failure_falls_back_and_is_not_retried_in_window(self):
        with patch.object(cnt, "_load_cached", return_value={}), \
             patch.object(cnt, "_save_cached") as save, \
             patch.object(cnt, "chat_completion", side_effect=LLMConnectionError("down")) as chat:
            first = cnt.localize_competitors(1, [{"name": "Acme"}], locale="ar")
            cnt.localize_competitors(1, [{"name": "Acme"}], locale="ar")
        self.assertEqual(first[0]["display_name"], "Acme")
        self.assertEqual(chat.call_count, 1)
        save.assert_not_called()

    def test_timeout_pauses_like_a_provider_failure(self):
        names = [f"C{i:03d}" for i in range(cnt.TRANSLATION_BATCH_SIZE + 1)]
        with patch.object(cnt, "_load_cached", return_value={}),              patch.object(cnt, "_save_cached"),              patch.object(cnt, "chat_completion", side_effect=LLMTimeoutError("slow")) as chat:
            cnt.translate_competitor_names(1, names, locale="ar")
            cnt.translate_competitor_names(1, names, locale="ar")
        self.assertEqual(chat.call_count, 1)

    def test_force_retries_through_the_failure_pause(self):
        with patch.object(cnt, "_load_cached", return_value={}), \
             patch.object(cnt, "_save_cached"), \
             patch.object(cnt, "chat_completion", side_effect=[LLMConnectionError("down"), _fake_chat]) as chat:
            first = cnt.localize_competitors(1, [{"name": "Acme"}], locale="ar")
            paused = cnt.localize_competitors(1, [{"name": "Acme"}], locale="ar")
            chat.side_effect = _fake_chat
            forced = cnt.localize_competitors(1, [{"name": "Acme"}], locale="ar", force=True)
        self.assertEqual(first[0]["display_name"], "Acme")
        self.assertEqual(paused[0]["display_name"], "Acme")
        self.assertEqual(forced[0]["display_name"], "ar:Acme")
        self.assertEqual(chat.call_count, 2)
        self.assertNotIn("ar", cnt._failure_cache)

    def test_mangled_batch_keeps_source_names_without_pausing(self):
        names = [f"C{i:03d}" for i in range(cnt.TRANSLATION_BATCH_SIZE + 1)]
        responses = [json.dumps({"names": []}), json.dumps({"names": ["ar:last"]})]
        with patch.object(cnt, "_load_cached", return_value={}), \
             patch.object(cnt, "_save_cached") as save, \
             patch.object(cnt, "chat_completion", side_effect=responses) as chat:
            result = cnt.translate_competitor_names(1, names, locale="ar")
        self.assertEqual(chat.call_count, 2)
        save.assert_called_once_with(1, "ar", {names[-1]: "ar:last"})
        self.assertEqual(result[names[0]], names[0])
        self.assertEqual(result[names[-1]], "ar:last")
        self.assertNotIn("ar", cnt._failure_cache)

    def test_findings_get_a_competitor_display_name(self):
        findings = [{"id": 1, "competitor_name": "Acme"}, {"id": 2, "competitor_name": None}]
        with patch.object(cnt, "_load_cached", return_value={"Acme": "أكمي"}), \
             patch.object(cnt, "chat_completion") as chat:
            result = cnt.localize_finding_names(1, findings, locale="ar")
        chat.assert_not_called()
        self.assertEqual([r["competitor_display_name"] for r in result], ["أكمي", None])


if __name__ == "__main__":
    unittest.main()
