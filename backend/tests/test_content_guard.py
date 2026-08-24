"""content_guard keeps consent/search pages out of a study's evidence.

Only imported articles can carry these URLs (a document candidate has none),
but a JSONL export from a crawler carries them routinely.
"""

import unittest

import content_guard


class BlockedDomainTests(unittest.TestCase):
    def test_google_domains_are_blocked(self):
        self.assertTrue(content_guard.is_blocked_domain("https://news.google.com/search?q=ev"))
        self.assertTrue(content_guard.is_blocked_domain("https://consent.google.com/ml?continue=x"))

    def test_www_prefix_is_ignored(self):
        self.assertTrue(content_guard.is_blocked_domain("https://www.google.com/anything"))

    def test_publisher_domains_are_not_blocked(self):
        self.assertFalse(content_guard.is_blocked_domain("https://news.example.com/story"))

    def test_missing_or_malformed_url_is_not_blocked(self):
        self.assertFalse(content_guard.is_blocked_domain(""))
        self.assertFalse(content_guard.is_blocked_domain(None))
        self.assertFalse(content_guard.is_blocked_domain("not a url"))


class ConsentTitleTests(unittest.TestCase):
    def test_consent_interstitial_titles_are_recognized(self):
        self.assertTrue(content_guard.is_consent_title("Before you continue to Google Search"))
        self.assertTrue(content_guard.is_consent_title("Sign in - Google Accounts"))

    def test_ordinary_headline_is_not_a_consent_title(self):
        self.assertFalse(content_guard.is_consent_title("Cafe chain opens third roastery"))

    def test_empty_title_is_not_a_consent_title(self):
        self.assertFalse(content_guard.is_consent_title(""))


class IsBlockedArticleTests(unittest.TestCase):
    def test_either_signal_blocks(self):
        self.assertTrue(content_guard.is_blocked_article("https://news.google.com/x", "Anything"))
        self.assertTrue(content_guard.is_blocked_article("https://news.example.com/x",
                                                        "Before you continue to Google"))

    def test_a_real_article_passes(self):
        self.assertFalse(content_guard.is_blocked_article("https://news.example.com/x",
                                                          "Cafe chain opens third roastery"))

    def test_a_document_candidate_passes(self):
        """Document-derived articles carry a synthetic url and no publisher
        title; nothing here should reject them."""
        self.assertFalse(content_guard.is_blocked_article(
            "document://project-document/3/article/7", "Respondent 12 on delivery times"))


if __name__ == "__main__":
    unittest.main()
