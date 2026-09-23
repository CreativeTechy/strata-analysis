import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.articles import iffy_dataset


class ActiveRatingsCacheMixin:
    """_ratings_for_dataset() is cached per dataset id (see its own
    docstring) - every test clears it on both ends so one test's mocked DB
    rows never leak into another's."""

    def setUp(self):
        iffy_dataset.clear_cache()

    def tearDown(self):
        iffy_dataset.clear_cache()


class LookupTests(ActiveRatingsCacheMixin, unittest.TestCase):
    def test_no_database_configured_returns_none_without_querying(self):
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", ""), \
             patch("services.articles.iffy_dataset.db.fetch_one") as mock_fetch_one:
            result = iffy_dataset.lookup("some-blog.example")
        self.assertIsNone(result)
        mock_fetch_one.assert_not_called()

    def test_blank_domain_returns_none_without_querying(self):
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.iffy_dataset.db.fetch_one") as mock_fetch_one:
            result = iffy_dataset.lookup("")
        self.assertIsNone(result)
        mock_fetch_one.assert_not_called()

    def test_no_active_dataset_returns_none(self):
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.iffy_dataset.db.fetch_one", return_value=None):
            result = iffy_dataset.lookup("some-blog.example")
        self.assertIsNone(result)

    def test_exact_domain_match(self):
        rating = {"domain": "some-blog.example", "publisher_name": "Some Blog", "factual_rating": "LOW"}
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.iffy_dataset.db.fetch_one", return_value={"id": 1}), \
             patch("services.articles.iffy_dataset.db.fetch_all", return_value=[rating]):
            result = iffy_dataset.lookup("some-blog.example")
        self.assertEqual(result, rating)

    def test_subdomain_inherits_the_parent_domains_rating(self):
        rating = {"domain": "some-blog.example", "factual_rating": "LOW"}
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.iffy_dataset.db.fetch_one", return_value={"id": 1}), \
             patch("services.articles.iffy_dataset.db.fetch_all", return_value=[rating]):
            result = iffy_dataset.lookup("amp.some-blog.example")
        self.assertEqual(result, rating)

    def test_unlisted_domain_returns_none_not_a_positive_rating(self):
        rating = {"domain": "some-blog.example", "factual_rating": "LOW"}
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.iffy_dataset.db.fetch_one", return_value={"id": 1}), \
             patch("services.articles.iffy_dataset.db.fetch_all", return_value=[rating]):
            result = iffy_dataset.lookup("reuters.com")
        self.assertIsNone(result)

    def test_query_error_returns_none_instead_of_raising(self):
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.iffy_dataset.db.fetch_one", side_effect=RuntimeError("boom")):
            result = iffy_dataset.lookup("some-blog.example")
        self.assertIsNone(result)

    def test_ratings_for_one_dataset_id_are_cached_across_calls_until_cleared(self):
        """The (potentially large) per-dataset ratings table is cached per
        dataset id - two lookups against the same active dataset id must
        not re-fetch it. The active-dataset-id check itself is deliberately
        NOT cached (see test_a_newly_activated_dataset_is_picked_up_without_
        clearing_the_cache below) - that's what lets a different process's
        import become visible here without a restart."""
        rating = {"domain": "some-blog.example", "factual_rating": "LOW"}
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.iffy_dataset.db.fetch_one", return_value={"id": 1}), \
             patch("services.articles.iffy_dataset.db.fetch_all", return_value=[rating]) as mock_fetch_all:
            iffy_dataset.lookup("some-blog.example")
            iffy_dataset.lookup("reuters.com")
        mock_fetch_all.assert_called_once()

    def test_a_newly_activated_dataset_is_picked_up_without_clearing_the_cache(self):
        """Regression test: import_records() runs clear_cache() in the
        operator script's own process, never in a running backend's - so a
        backend that already resolved an Iffy lookup before an import must
        still pick up the newly active dataset on its very next lookup, with
        no call to clear_cache() in this process at all."""
        old_rating = {"domain": "old-blog.example", "factual_rating": "LOW"}
        new_rating = {"domain": "new-blog.example", "factual_rating": "LOW"}
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.iffy_dataset.db.fetch_one", return_value={"id": 1}), \
             patch("services.articles.iffy_dataset.db.fetch_all", return_value=[old_rating]):
            self.assertIsNotNone(iffy_dataset.lookup("old-blog.example"))

        # A second dataset activates - a different id, as a fresh insert
        # always gets (no clear_cache() call here, simulating another process).
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.iffy_dataset.db.fetch_one", return_value={"id": 2}), \
             patch("services.articles.iffy_dataset.db.fetch_all", return_value=[new_rating]):
            self.assertIsNotNone(iffy_dataset.lookup("new-blog.example"))
            self.assertIsNone(iffy_dataset.lookup("old-blog.example"))


class ActiveDatasetMetadataTests(ActiveRatingsCacheMixin, unittest.TestCase):
    def test_no_database_configured_returns_none(self):
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", ""):
            self.assertIsNone(iffy_dataset.active_dataset_metadata())

    def test_no_dataset_imported_returns_none(self):
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.iffy_dataset.db.fetch_one", return_value=None):
            self.assertIsNone(iffy_dataset.active_dataset_metadata())

    def test_returns_the_active_datasets_provenance(self):
        row = {
            "version": "iffy-abc123", "source_url": iffy_dataset.DEFAULT_FEED_URL,
            "license": "CC BY 4.0", "record_count": 1200, "imported_at": "2026-01-01T00:00:00Z",
        }
        with patch("services.articles.iffy_dataset.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.iffy_dataset.db.fetch_one", return_value=row):
            result = iffy_dataset.active_dataset_metadata()
        self.assertEqual(result, {
            "provider": "Iffy.news", "version": "iffy-abc123", "source_url": iffy_dataset.DEFAULT_FEED_URL,
            "license": "CC BY 4.0", "record_count": 1200, "imported_at": "2026-01-01T00:00:00Z",
        })


class CleanRecordsTests(unittest.TestCase):
    def test_extracts_and_normalizes_the_iffy_feeds_own_column_names(self):
        records = [{
            "Domain": "Some-Blog.EXAMPLE", "Name": "Some Blog", "MBFC Fact": "LOW",
            "MBFC cred": "Low Credibility", "Media Bias/Fact Check": "https://mediabiasfactcheck.com/some-blog/",
        }]
        cleaned = iffy_dataset._clean_records(records)
        self.assertEqual(cleaned, [{
            "domain": "some-blog.example", "publisher_name": "Some Blog", "factual_rating": "LOW",
            "credibility_rating": "Low Credibility", "review_url": "https://mediabiasfactcheck.com/some-blog/",
            "raw_data": records[0],
        }])

    def test_records_with_no_resolvable_domain_are_dropped(self):
        cleaned = iffy_dataset._clean_records([{"Name": "No domain here"}, {"Domain": ""}])
        self.assertEqual(cleaned, [])

    def test_non_dict_records_are_skipped_without_raising(self):
        cleaned = iffy_dataset._clean_records(["not-a-dict", None, 42])
        self.assertEqual(cleaned, [])

    def test_duplicate_domains_keep_the_last_record(self):
        records = [
            {"Domain": "some-blog.example", "Name": "First"},
            {"Domain": "some-blog.example", "Name": "Second"},
        ]
        cleaned = iffy_dataset._clean_records(records)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["publisher_name"], "Second")


class ImportRecordsTests(unittest.TestCase):
    def _make_records(self, count):
        return [{"Domain": f"blog-{i}.example", "Name": f"Blog {i}"} for i in range(count)]

    def test_rejects_a_dataset_below_the_minimum_record_count(self):
        with self.assertRaises(ValueError):
            iffy_dataset.import_records(self._make_records(5), minimum_records=100)

    def test_imports_versions_and_activates_the_dataset(self):
        records = self._make_records(150)
        fake_cursor_calls = []

        class FakeCursor:
            def execute(self, sql, params=None):
                fake_cursor_calls.append((sql, params))

            def executemany(self, sql, seq_of_params):
                fake_cursor_calls.append((sql, list(seq_of_params)))

            def fetchone(self):
                return {"id": 42}

        class FakeTransaction:
            def __enter__(self):
                return FakeCursor()

            def __exit__(self, *exc_info):
                return False

        with patch("services.articles.iffy_dataset.db.transaction", return_value=FakeTransaction()), \
             patch.object(iffy_dataset, "clear_cache") as mock_clear_cache:
            result = iffy_dataset.import_records(records, source_url="https://example.com/feed")

        self.assertEqual(result["provider"], "Iffy.news")
        self.assertEqual(result["domains_imported"], 150)
        self.assertTrue(result["version"].startswith("iffy-"))
        mock_clear_cache.assert_called_once()

        # The dataset insert deactivates any prior version and activates
        # this one - never two datasets active for the same provider.
        insert_sql = fake_cursor_calls[1][0]
        self.assertIn("active", insert_sql)
        self.assertIn("on conflict (provider, version)", insert_sql)


if __name__ == "__main__":
    unittest.main()
