import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.articles import source_trust


class ResolveManyTests(unittest.TestCase):
    def test_empty_sources_returns_empty_without_querying(self):
        with patch("services.articles.source_trust.db.fetch_all") as mock_fetch_all:
            result = source_trust.resolve_many([])
        self.assertEqual(result, {})
        mock_fetch_all.assert_not_called()

    def test_operator_override_wins_over_the_seeded_default(self):
        sources = [{"key": "real:reuters.com", "type": "real", "label": "reuters.com"}]
        override_row = {
            "source_key": "real:reuters.com", "source_type": "real", "tier": "untrusted",
            "reason": "Known to syndicate unverified claims.",
            "set_by_name": "alice", "updated_at": "2026-01-01T00:00:00Z", "project_id": 1,
        }
        with patch("services.articles.source_trust.db.fetch_all", return_value=[override_row]):
            result = source_trust.resolve_many(sources, project_id=1)
        self.assertEqual(result["real:reuters.com"], {
            "tier": "untrusted", "reason": "Known to syndicate unverified claims.",
            "set_by": "alice", "updated_at": "2026-01-01T00:00:00Z", "is_default": False,
        })

    def test_a_same_project_viewer_sees_the_override_reason_and_author(self):
        sources = [{"key": "real:reuters.com", "type": "real", "label": "reuters.com"}]
        override_row = {
            "source_key": "real:reuters.com", "source_type": "real", "tier": "untrusted",
            "reason": "Flagged for the Acme engagement.", "set_by_name": "alice",
            "updated_at": "2026-01-01T00:00:00Z", "project_id": 1,
        }
        with patch("services.articles.source_trust.db.fetch_all", return_value=[override_row]):
            result = source_trust.resolve_many(sources, project_id=1)
        self.assertEqual(result["real:reuters.com"]["reason"], "Flagged for the Acme engagement.")
        self.assertEqual(result["real:reuters.com"]["set_by"], "alice")

    def test_a_different_project_viewer_sees_the_tier_but_not_the_reason_or_author(self):
        """A "real:" override's tier is intentionally global (see
        migrations/0026's own note), but its free-text reason/author can name
        specifics from the project it was made in - those must not leak to a
        second project's viewer just because the tier itself is shared."""
        sources = [{"key": "real:reuters.com", "type": "real", "label": "reuters.com"}]
        override_row = {
            "source_key": "real:reuters.com", "source_type": "real", "tier": "untrusted",
            "reason": "Flagged for the Acme engagement.", "set_by_name": "alice",
            "updated_at": "2026-01-01T00:00:00Z", "project_id": 1,
        }
        with patch("services.articles.source_trust.db.fetch_all", return_value=[override_row]):
            result = source_trust.resolve_many(sources, project_id=2)
        self.assertEqual(result["real:reuters.com"]["tier"], "untrusted")
        self.assertIsNone(result["real:reuters.com"]["reason"])
        self.assertIsNone(result["real:reuters.com"]["set_by"])

    def test_a_legacy_override_with_no_recorded_project_is_never_redacted(self):
        """A row saved before project scoping existed (project_id null) is
        treated as same-project rather than newly hiding something that was
        already visible - see migrations/0028's own note."""
        sources = [{"key": "real:reuters.com", "type": "real", "label": "reuters.com"}]
        override_row = {
            "source_key": "real:reuters.com", "source_type": "real", "tier": "untrusted",
            "reason": "Known to syndicate unverified claims.", "set_by_name": "alice",
            "updated_at": "2026-01-01T00:00:00Z", "project_id": None,
        }
        with patch("services.articles.source_trust.db.fetch_all", return_value=[override_row]):
            result = source_trust.resolve_many(sources, project_id=2)
        self.assertEqual(result["real:reuters.com"]["reason"], "Known to syndicate unverified claims.")

    def test_a_document_override_is_never_redacted_regardless_of_viewer_project(self):
        """A "document:" key already embeds one project's own document id -
        only that project's list_project_sources() can ever compute the same
        key, so there is no cross-project risk to redact here."""
        sources = [{"key": "document:document://project-document/1", "type": "document", "label": "report.pdf"}]
        override_row = {
            "source_key": "document:document://project-document/1", "source_type": "document", "tier": "untrusted",
            "reason": "Ghost-written, per the operator's own review.", "set_by_name": "alice",
            "updated_at": "2026-01-01T00:00:00Z", "project_id": 1,
        }
        with patch("services.articles.source_trust.db.fetch_all", return_value=[override_row]):
            result = source_trust.resolve_many(sources, project_id=99)
        self.assertEqual(result["document:document://project-document/1"]["reason"], "Ghost-written, per the operator's own review.")

    def test_real_source_on_the_allowlist_defaults_to_trusted_without_an_override(self):
        sources = [{"key": "real:reuters.com", "type": "real", "label": "reuters.com"}]
        with patch("services.articles.source_trust.db.fetch_all", return_value=[]), \
             patch("services.articles.source_trust.iffy_dataset.lookup") as mock_lookup:
            result = source_trust.resolve_many(sources)
        self.assertEqual(result["real:reuters.com"], {
            "tier": "trusted", "reason": None, "set_by": None, "updated_at": None, "is_default": True,
        })
        # The allowlist match is decisive on its own - no need to even
        # consult the (much larger, DB-backed) Iffy dataset for a hit here.
        mock_lookup.assert_not_called()

    def test_real_source_off_the_allowlist_defaults_to_unknown_not_untrusted(self):
        """unknown (not yet assessed) must never collapse into untrusted
        (assessed and rejected) - that collapse is exactly what made the
        older boolean articles.verified column useless as a trust signal."""
        sources = [{"key": "real:some-blog.example", "type": "real", "label": "some-blog.example"}]
        with patch("services.articles.source_trust.db.fetch_all", return_value=[]), \
             patch("services.articles.source_trust.iffy_dataset.lookup", return_value=None):
            result = source_trust.resolve_many(sources)
        self.assertEqual(result["real:some-blog.example"]["tier"], "unknown")

    def test_real_source_in_the_iffy_dataset_defaults_to_untrusted_with_a_reason(self):
        sources = [{"key": "real:some-blog.example", "type": "real", "label": "some-blog.example"}]
        concern = {"domain": "some-blog.example", "factual_rating": "LOW", "credibility_rating": "Low Credibility"}
        with patch("services.articles.source_trust.db.fetch_all", return_value=[]), \
             patch("services.articles.source_trust.iffy_dataset.lookup", return_value=concern):
            result = source_trust.resolve_many(sources)
        entry = result["real:some-blog.example"]
        self.assertEqual(entry["tier"], "untrusted")
        self.assertTrue(entry["is_default"])
        self.assertIn("Iffy.news", entry["reason"])
        self.assertIn("LOW", entry["reason"])
        self.assertEqual(entry["set_by"], "Iffy.news")

    def test_operator_override_wins_over_an_iffy_dataset_hit_too(self):
        """A hand-reviewed 'trusted' override must survive even when the
        wider, DB-backed Iffy dataset would otherwise flag the domain -
        an operator's own review always outranks any seeded default."""
        sources = [{"key": "real:some-blog.example", "type": "real", "label": "some-blog.example"}]
        override_row = {
            "source_key": "real:some-blog.example", "tier": "trusted",
            "reason": "Verified directly with the publisher.", "set_by_name": "alice", "updated_at": "2026-01-01T00:00:00Z",
        }
        with patch("services.articles.source_trust.db.fetch_all", return_value=[override_row]), \
             patch("services.articles.source_trust.iffy_dataset.lookup") as mock_lookup:
            result = source_trust.resolve_many(sources)
        self.assertEqual(result["real:some-blog.example"]["tier"], "trusted")
        mock_lookup.assert_not_called()

    def test_document_source_defaults_to_unknown_not_trusted(self):
        """An uploaded document has no publisher identity of its own, so it
        must never seed as trusted just because nothing has overridden it."""
        sources = [{"key": "document:document://project-document/1", "type": "document", "label": "report.pdf"}]
        with patch("services.articles.source_trust.db.fetch_all", return_value=[]), \
             patch("services.articles.source_trust.iffy_dataset.lookup") as mock_lookup:
            result = source_trust.resolve_many(sources)
        self.assertEqual(result["document:document://project-document/1"]["tier"], "unknown")
        # A "document:" source has no publisher domain to look Iffy up by.
        mock_lookup.assert_not_called()

    def test_query_error_falls_back_to_seeded_defaults_instead_of_raising(self):
        sources = [{"key": "real:reuters.com", "type": "real", "label": "reuters.com"}]
        with patch("services.articles.source_trust.db.fetch_all", side_effect=RuntimeError("boom")), \
             patch("services.articles.source_trust.iffy_dataset.lookup", return_value=None):
            result = source_trust.resolve_many(sources)
        self.assertEqual(result["real:reuters.com"]["tier"], "trusted")
        self.assertTrue(result["real:reuters.com"]["is_default"])

    def test_sources_without_a_key_are_skipped(self):
        with patch("services.articles.source_trust.db.fetch_all", return_value=[]):
            result = source_trust.resolve_many([{"type": "real", "label": "x"}])
        self.assertEqual(result, {})


class SetTierTests(unittest.TestCase):
    def test_rejects_an_unknown_tier(self):
        with self.assertRaises(ValueError):
            source_trust.set_tier("real:reuters.com", "real", "very-trusted", "why not", {"id": 1})

    def test_rejects_an_invalid_source_type(self):
        with self.assertRaises(ValueError):
            source_trust.set_tier("real:reuters.com", "rss-feed", "trusted", "why not", {"id": 1})

    def test_requires_a_reason_even_to_reset_to_unknown(self):
        with self.assertRaises(ValueError):
            source_trust.set_tier("real:reuters.com", "real", "unknown", "   ", {"id": 1})

    def test_records_an_audit_row_and_upserts_the_current_state_in_one_transaction(self):
        """Both writes go through the same cursor inside one db.transaction()
        - not two independent db.execute()/db.fetch_one() calls (each its
        own connection/commit) - so the audit trail can never end up
        recording a change that the live source_trust row doesn't actually
        reflect (e.g. the upsert failing after the audit row already
        committed)."""
        user = {"id": 7, "username": "alice"}
        calls = []

        class FakeCursor:
            def execute(self, sql, params=None):
                calls.append((sql, params))

            def fetchone(self):
                return {"tier": "trusted"}

        class FakeTransaction:
            def __enter__(self):
                return FakeCursor()

            def __exit__(self, *exc_info):
                return False

        with patch("services.articles.source_trust.db.transaction", return_value=FakeTransaction()) as mock_transaction:
            result = source_trust.set_tier("real:reuters.com", "real", "trusted", "Wire service.", user, project_id=3)

        mock_transaction.assert_called_once()
        self.assertEqual(len(calls), 2)

        insert_sql, insert_params = calls[0]
        self.assertIn("source_trust_reviews", insert_sql)
        self.assertEqual(insert_params, ("real:reuters.com", "real", "trusted", "Wire service.", 7, "alice", 3))

        upsert_sql, upsert_params = calls[1]
        self.assertIn("on conflict (source_key) do update", upsert_sql)
        self.assertEqual(upsert_params, ("real:reuters.com", "real", "trusted", "Wire service.", 7, "alice", 3))
        self.assertEqual(result, {"tier": "trusted"})
