"""Unit tests for services/articles/idea_comparison_translation.py: default
locale no-op, cache reuse, chunk fallback, failure cooldown, and that a
localized detail keeps the canonical fact text for editing."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from services.articles import idea_comparison_translation as t

MOD = "services.articles.idea_comparison_translation"
COMPARISON = {
    "idea": "Slow checkout", "summary": "Sources disagree",
    "sources": [{"value": "Takes 5 minutes", "title": "Post", "excerpt": "ex"}],
    "facts": [{"id": 1, "fact_text": "Checkout is slow", "stated_value": "5 min"}],
}


def fake_translate(texts, locale):
    return [f"ar:{x}" for x in texts]


class TranslationTests(unittest.TestCase):
    def setUp(self):
        t._failure_cache.clear()

    def test_default_locale_is_noop(self):
        with patch(f"{MOD}._translate_missing") as m:
            out = t.localize_idea_comparisons([COMPARISON], project_id=1, locale=config.DEFAULT_LOCALE)
        self.assertEqual(out, [COMPARISON])
        m.assert_not_called()

    def test_cached_text_is_not_retranslated(self):
        cached = {"Slow checkout": "cached"}
        with patch(f"{MOD}._load_cached", return_value=cached), \
             patch(f"{MOD}._save_cached"), \
             patch(f"{MOD}._translate", side_effect=fake_translate) as tr:
            out = t.localize_idea_comparisons([COMPARISON], project_id=1, locale="ar")
        self.assertEqual(out[0]["idea"], "cached")
        self.assertNotIn("Slow checkout", [x for call in tr.call_args_list for x in call.args[0]])

    def test_wrong_shape_chunk_falls_back_item_by_item(self):
        calls = []

        def flaky(texts, locale):
            calls.append(len(texts))
            if len(texts) > 1:
                raise RuntimeError("wrong shape")
            return [f"ar:{texts[0]}"]

        with patch(f"{MOD}._load_cached", return_value={}), patch(f"{MOD}._save_cached"), \
             patch(f"{MOD}._translate", side_effect=flaky):
            out = t.localize_idea_comparisons([COMPARISON], project_id=1, locale="ar")
        self.assertEqual(out[0]["idea"], "ar:Slow checkout")

    def test_failure_keeps_original_and_sets_cooldown(self):
        with patch(f"{MOD}._load_cached", return_value={}), patch(f"{MOD}._save_cached"), \
             patch(f"{MOD}._translate", side_effect=RuntimeError("down")) as tr:
            out = t.localize_idea_comparisons([COMPARISON], project_id=1, locale="ar")
            first_calls = tr.call_count
            t.localize_idea_comparisons([COMPARISON], project_id=1, locale="ar")
        self.assertEqual(out[0]["idea"], "Slow checkout")
        self.assertEqual(tr.call_count, first_calls)

    def test_translate_texts_fails_fast_without_item_retries(self):
        texts = [f"text {i}" for i in range(20)]
        with patch(f"{MOD}._load_cached", return_value={}), patch(f"{MOD}._save_cached"),              patch(f"{MOD}._translate", side_effect=RuntimeError("timeout")) as tr:
            out = t.translate_texts(texts, project_id=1, locale="ar")
        self.assertEqual(out, {})
        self.assertEqual(tr.call_count, 1)

    def test_translate_texts_is_noop_for_default_locale(self):
        with patch(f"{MOD}._translate_missing") as m:
            self.assertEqual(t.translate_texts(["a"], project_id=1, locale=config.DEFAULT_LOCALE), {})
        m.assert_not_called()

    def test_detail_keeps_canonical_fact_text_for_editing(self):
        with patch(f"{MOD}._load_cached", return_value={}), patch(f"{MOD}._save_cached"), \
             patch(f"{MOD}._translate", side_effect=fake_translate):
            out = t.localize_idea_comparison_detail(COMPARISON, project_id=1, locale="ar")
        fact = out["facts"][0]
        self.assertEqual(fact["fact_text"], "ar:Checkout is slow")
        self.assertEqual(fact["fact_text_original"], "Checkout is slow")
        self.assertEqual(fact["stated_value_original"], "5 min")


if __name__ == "__main__":
    unittest.main()
