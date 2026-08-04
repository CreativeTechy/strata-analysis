import os
import unittest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.competitors import competitors_store


class NormalizeSourceUrlTests(unittest.TestCase):
    def test_bare_domain_gets_https_prefix(self):
        self.assertEqual(competitors_store.normalize_source_url("example.com"), "https://example.com")

    def test_existing_scheme_is_kept(self):
        self.assertEqual(
            competitors_store.normalize_source_url("http://example.com/feed"),
            "http://example.com/feed",
        )

    def test_blank_is_rejected(self):
        self.assertIsNone(competitors_store.normalize_source_url(""))
        self.assertIsNone(competitors_store.normalize_source_url(None))

    def test_no_dotted_host_is_rejected(self):
        self.assertIsNone(competitors_store.normalize_source_url("not a url"))
        self.assertIsNone(competitors_store.normalize_source_url("https://localhost"))


if __name__ == "__main__":
    unittest.main()
