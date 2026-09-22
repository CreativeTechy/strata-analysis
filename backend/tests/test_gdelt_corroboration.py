import unittest
from unittest.mock import patch

from services.articles.gdelt_corroboration import (
    STATUS_BROAD,
    STATUS_NONE,
    build_query,
    summarize_results,
)


class GdeltCorroborationTests(unittest.TestCase):
    def test_build_query_uses_a_bounded_exact_title_phrase(self):
        query = build_query("One two three four five six seven eight nine ten eleven twelve thirteen")
        self.assertEqual(query, '"One two three four five six seven eight nine ten eleven twelve"')

    def test_short_title_is_rejected(self):
        with self.assertRaises(ValueError):
            build_query("Two words")

    @patch("services.articles.gdelt_corroboration.config.GDELT_BROAD_COVERAGE_DOMAINS", 2)
    @patch("services.articles.gdelt_corroboration.config.GDELT_MIN_TITLE_OVERLAP", 0.6)
    def test_counts_distinct_matching_domains_and_excludes_original(self):
        article = {"title": "City council approves new public transport plan", "source_domain": "origin.example"}
        payload = {"articles": [
            {"domain": "origin.example", "title": article["title"], "url": "https://origin.example/a"},
            {"domain": "one.example", "title": "City council approves new public transport plan", "url": "https://one.example/a"},
            {"domain": "one.example", "title": "City council approves new public transport plan today", "url": "https://one.example/b"},
            {"domain": "two.example", "title": "City council approves a new public transport plan", "url": "https://two.example/a"},
            {"domain": "noise.example", "title": "Unrelated sports result", "url": "https://noise.example/a"},
            {"domain": "unsafe.example", "title": article["title"], "url": "javascript:alert(1)"},
        ]}
        result = summarize_results(article, payload, '"City council approves"')
        self.assertEqual(result["status"], STATUS_BROAD)
        self.assertEqual(result["matching_domain_count"], 2)
        self.assertEqual({match["domain"] for match in result["matches"]}, {"one.example", "two.example"})

    def test_empty_results_do_not_claim_verification(self):
        result = summarize_results({"title": "A useful article title"}, {"articles": []}, '"useful article title"')
        self.assertEqual(result["status"], STATUS_NONE)
        self.assertIn("not proof", result["caveat"].lower())


if __name__ == "__main__":
    unittest.main()
