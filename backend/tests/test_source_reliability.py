import unittest

from services.articles.source_reliability import (
    STATUS_CONCERN,
    STATUS_NOT_ASSESSED,
    STATUS_NOT_LISTED,
    assess,
    match_rating,
    normalize_domain,
    resolve_source_domain,
)


class SourceDomainTests(unittest.TestCase):
    def test_normalizes_urls_and_subdomains(self):
        self.assertEqual(normalize_domain("https://WWW.News.Example.com/story"), "news.example.com")

    def test_rejects_internal_document_urls(self):
        self.assertIsNone(normalize_domain("document://project-document/4/article/9"))

    def test_prefers_original_provenance_url(self):
        article = {
            "url": "https://cached.example/story",
            "source_url": "document://project-document/4",
            "source_provenance": {"original_url": "https://publisher.example/news/1"},
        }
        self.assertEqual(resolve_source_domain(article), "publisher.example")


class IffyAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.dataset = {"version": "iffy-test"}
        self.ratings = {
            "example.com": {
                "domain": "example.com",
                "publisher_name": "Example",
                "factual_rating": "L",
                "credibility_rating": "L",
                "quality_score": 0.2,
                "provider_score": 0.1,
                "review_url": "https://review.example/example",
            }
        }

    def test_subdomain_matches_parent_publisher(self):
        rating = match_rating("news.example.com", self.ratings)
        self.assertEqual(rating["domain"], "example.com")

    def test_lookalike_domain_does_not_match(self):
        self.assertIsNone(match_rating("example.com.evil.test", self.ratings))

    def test_match_reports_concern_with_provider_evidence(self):
        result = assess({"url": "https://news.example.com/a"}, self.dataset, self.ratings)
        self.assertEqual(result["status"], STATUS_CONCERN)
        self.assertEqual(result["details"]["matched_domain"], "example.com")
        self.assertEqual(result["reference_url"], "https://review.example/example")

    def test_absence_is_not_treated_as_verified(self):
        result = assess({"url": "https://unrated.test/a"}, self.dataset, self.ratings)
        self.assertEqual(result["status"], STATUS_NOT_LISTED)
        self.assertIn("not listed", result["reason"].lower())

    def test_missing_origin_is_not_assessed(self):
        result = assess({"url": "document://project-document/2/article/1"}, self.dataset, self.ratings)
        self.assertEqual(result["status"], STATUS_NOT_ASSESSED)

    def test_identifiable_publisher_is_not_assessed_without_a_dataset(self):
        result = assess({"url": "https://publisher.example/story"}, None, {})
        self.assertEqual(result["status"], STATUS_NOT_ASSESSED)
        self.assertEqual(result["domain"], "publisher.example")
        self.assertIn("has not been imported", result["reason"])


if __name__ == "__main__":
    unittest.main()
