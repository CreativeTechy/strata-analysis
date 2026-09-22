import unittest
from unittest.mock import patch

from services.articles.gdelt_corroboration import (
    STATUS_BROAD,
    STATUS_LOW,
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
        self.assertEqual(result["status"], "some_coverage")
        self.assertEqual(result["matching_domain_count"], 2)
        self.assertEqual({match["domain"] for match in result["matches"]}, {"one.example", "two.example"})

    def test_empty_results_do_not_claim_verification(self):
        result = summarize_results({"title": "A useful article title"}, {"articles": []}, '"useful article title"')
        self.assertEqual(result["status"], STATUS_NONE)
        self.assertEqual(result["status"], "not_checked")
        self.assertIn("not proof", result["caveat"].lower())

    @patch("services.articles.gdelt_corroboration.config.GDELT_BROAD_COVERAGE_DOMAINS", 3)
    def test_subdomains_of_one_publisher_count_once(self):
        article = {"title": "City council approves new public transport plan", "url": "https://origin.example/story"}
        payload = {"articles": [
            {"url": f"https://{subdomain}.publisher.com/story", "title": article["title"]}
            for subdomain in ("news", "local", "mobile")
        ]}
        result = summarize_results(article, payload, '"City council approves"')
        self.assertEqual(result["matching_domain_count"], 1)
        self.assertNotEqual(result["status"], STATUS_BROAD)

    def test_opposing_headlines_do_not_raise_confidence(self):
        article = {"title": "City council approves new public transport plan", "url": "https://origin.example/story"}
        payload = {"articles": [
            {"url": f"https://{domain}/story", "title": "City council rejects new public transport plan"}
            for domain in ("one.example", "two.example", "three.example")
        ]}
        result = summarize_results(article, payload, '"City council approves"')
        self.assertEqual(result["status"], "some_coverage")
        self.assertEqual(result["supporting_domain_count"], 0)
        self.assertEqual(result["contradicting_domain_count"], 3)

    def test_different_title_quantities_are_not_matches(self):
        article = {"title": "Sales increased 20 percent in 2025", "url": "https://origin.example/story"}
        payload = {"articles": [{
            "url": "https://other.example/story",
            "title": "Sales increased 35 percent in 2025",
        }]}
        result = summarize_results(article, payload, '"Sales increased"')
        self.assertEqual(result["status"], STATUS_NONE)
        self.assertEqual(result["matching_domain_count"], 0)

    @patch("services.articles.gdelt_corroboration.config.GDELT_BROAD_COVERAGE_DOMAINS", 2)
    def test_mixed_reporting_from_one_domain_forces_review(self):
        article = {"title": "City council approves new public transport plan", "url": "https://origin.example/story"}
        payload = {"articles": [
            {"url": "https://one.example/support", "title": article["title"]},
            {"url": "https://two.example/support", "title": article["title"]},
            {"url": "https://three.example/support", "title": article["title"]},
            {"url": "https://three.example/conflict", "title": "City council rejects new public transport plan"},
        ]}
        result = summarize_results(article, payload, '"City council approves"')
        self.assertEqual(result["status"], "some_coverage")


if __name__ == "__main__":
    unittest.main()
