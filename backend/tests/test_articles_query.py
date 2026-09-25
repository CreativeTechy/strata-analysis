import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.articles import articles_query


class ListIdeaClustersForProjectTests(unittest.TestCase):
    def test_falsy_project_id_returns_empty_page_without_querying(self):
        with patch("services.articles.articles_query.db.fetch_all") as mock_fetch_all:
            result = articles_query.list_idea_clusters_for_project(None)
        self.assertEqual(result, {"clusters": [], "total": 0, "limit": 50, "offset": 0})
        mock_fetch_all.assert_not_called()

    def test_no_database_configured_returns_empty_page(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", ""):
            result = articles_query.list_idea_clusters_for_project(1)
        self.assertEqual(result["clusters"], [])
        self.assertEqual(result["total"], 0)

    def test_returns_rows_and_total_from_the_query(self):
        rows = [{"id": 1, "idea": "charging is slow", "frequency_estimate": 3}]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=rows) as mock_fetch_all:
                with patch("services.articles.articles_query.db.fetch_one", return_value={"total": 7}):
                    result = articles_query.list_idea_clusters_for_project(1, limit=10, offset=5)
        self.assertEqual(result, {"clusters": rows, "total": 7, "limit": 10, "offset": 5})
        args, _ = mock_fetch_all.call_args
        self.assertIn("idea_clusters", args[0])

    def test_query_error_returns_empty_page_instead_of_raising(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", side_effect=RuntimeError("boom")):
                result = articles_query.list_idea_clusters_for_project(1)
        self.assertEqual(result["clusters"], [])


class ListArticlesForIdeaClusterTests(unittest.TestCase):
    def test_no_database_configured_returns_none(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", ""):
            self.assertIsNone(articles_query.list_articles_for_idea_cluster(1, 2))

    def test_cluster_not_in_project_returns_none(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_one", return_value=None):
                self.assertIsNone(articles_query.list_articles_for_idea_cluster(1, 2))

    def test_returns_articles_page_when_cluster_belongs_to_project(self):
        article_rows = [{"id": 10, "title": "EV Review"}]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_one", side_effect=[{"id": 1}, {"total": 1}]):
                with patch("services.articles.articles_query.db.fetch_all", return_value=article_rows):
                    result = articles_query.list_articles_for_idea_cluster(1, 2)
        self.assertEqual(result, {"articles": article_rows, "total": 1, "limit": 10, "offset": 0})

    def test_query_error_returns_none(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_one", side_effect=RuntimeError("boom")):
                self.assertIsNone(articles_query.list_articles_for_idea_cluster(1, 2))


class ListProjectSourcesTests(unittest.TestCase):
    def test_falsy_project_id_returns_empty_without_querying(self):
        with patch("services.articles.articles_query.db.fetch_all") as mock_fetch_all:
            result = articles_query.list_project_sources(None)
        self.assertEqual(result, {"sources": [], "total": 0, "total_articles": 0, "limit": 20, "offset": 0})
        mock_fetch_all.assert_not_called()

    def test_no_database_configured_returns_empty(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", ""):
            result = articles_query.list_project_sources(1)
        self.assertEqual(result, {"sources": [], "total": 0, "total_articles": 0, "limit": 20, "offset": 0})

    def test_query_error_returns_empty_instead_of_raising(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", side_effect=RuntimeError("boom")):
                result = articles_query.list_project_sources(1)
        self.assertEqual(result, {"sources": [], "total": 0, "total_articles": 0, "limit": 20, "offset": 0})

    def test_groups_real_urls_by_hostname_and_document_urls_by_source_url(self):
        rows = [
            {"id": 1, "title": "A1", "url": "https://nytimes.com/a1", "source": "doc.pdf",
             "source_url": "document://project-document/9", "published_at": datetime(2024, 1, 3)},
            {"id": 2, "title": "A2", "url": "https://nytimes.com/a2", "source": "doc.pdf",
             "source_url": "document://project-document/9", "published_at": datetime(2024, 1, 5)},
            {"id": 3, "title": "D1", "url": "document://project-document/1/article/3", "source": "report.pdf",
             "source_url": "document://project-document/1", "published_at": None},
            {"id": 4, "title": "D2", "url": "document://project-document/1/article/4", "source": "report.pdf",
             "source_url": "document://project-document/1", "published_at": datetime(2024, 1, 1)},
            {"id": 5, "title": "D3", "url": "document://project-document/1/article/5", "source": "report.pdf",
             "source_url": "document://project-document/1", "published_at": datetime(2024, 1, 2)},
        ]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=rows) as mock_fetch_all, \
                 patch("services.articles.articles_query.resolve_source_trust", return_value={}):
                result = articles_query.list_project_sources(1)

        mock_fetch_all.assert_called_once()
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["total_articles"], 5)
        self.assertEqual(result["limit"], 20)
        self.assertEqual(result["offset"], 0)
        self.assertEqual(len(result["sources"]), 2)

        # The document (3 articles) outranks the real outlet (2 articles).
        document_source, real_source = result["sources"]
        self.assertEqual(document_source["type"], "document")
        self.assertEqual(document_source["label"], "report.pdf")
        self.assertEqual(document_source["url"], "document://project-document/1")
        self.assertEqual(document_source["article_count"], 3)
        self.assertEqual(document_source["latest_published_at"], datetime(2024, 1, 2))
        self.assertEqual([a["id"] for a in document_source["articles"]], [5, 4, 3])
        self.assertIsNone(document_source["articles"][0]["url"])

        self.assertEqual(real_source["type"], "real")
        self.assertEqual(real_source["label"], "nytimes.com")
        self.assertEqual(real_source["url"], "https://nytimes.com")
        self.assertEqual(real_source["article_count"], 2)
        self.assertEqual(real_source["latest_published_at"], datetime(2024, 1, 5))
        self.assertEqual([a["id"] for a in real_source["articles"]], [2, 1])
        self.assertEqual(real_source["articles"][0]["url"], "https://nytimes.com/a2")

    def test_limit_and_offset_page_the_source_groups(self):
        rows = [
            {"id": 1, "title": "A1", "url": "https://nytimes.com/a1", "source": "doc.pdf",
             "source_url": "document://project-document/9", "published_at": datetime(2024, 1, 3)},
            {"id": 2, "title": "A2", "url": "https://nytimes.com/a2", "source": "doc.pdf",
             "source_url": "document://project-document/9", "published_at": datetime(2024, 1, 5)},
            {"id": 3, "title": "D1", "url": "document://project-document/1/article/3", "source": "report.pdf",
             "source_url": "document://project-document/1", "published_at": None},
            {"id": 4, "title": "D2", "url": "document://project-document/1/article/4", "source": "report.pdf",
             "source_url": "document://project-document/1", "published_at": datetime(2024, 1, 1)},
            {"id": 5, "title": "D3", "url": "document://project-document/1/article/5", "source": "report.pdf",
             "source_url": "document://project-document/1", "published_at": datetime(2024, 1, 2)},
        ]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=rows), \
                 patch("services.articles.articles_query.resolve_source_trust", return_value={}):
                result = articles_query.list_project_sources(1, limit=1, offset=1)

        # Same two groups as above (document first, then the real outlet),
        # but only the second page of one source group is returned.
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["limit"], 1)
        self.assertEqual(result["offset"], 1)
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["sources"][0]["type"], "real")

    def test_tied_groups_sort_deterministically_regardless_of_row_order(self):
        # Two different documents ("report.pdf" uploaded twice) tie on both
        # article_count and label, so only their distinct source_url (via
        # group["key"]) can break the tie deterministically.
        rows_forward = [
            {"id": 1, "title": "D1", "url": "document://project-document/1/article/1", "source": "report.pdf",
             "source_url": "document://project-document/1", "published_at": datetime(2024, 1, 1)},
            {"id": 2, "title": "D2", "url": "document://project-document/2/article/2", "source": "report.pdf",
             "source_url": "document://project-document/2", "published_at": datetime(2024, 1, 2)},
        ]
        rows_reversed = list(reversed(rows_forward))

        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.articles_query.resolve_source_trust", return_value={}):
            with patch("services.articles.articles_query.db.fetch_all", return_value=rows_forward):
                forward = articles_query.list_project_sources(1)
            with patch("services.articles.articles_query.db.fetch_all", return_value=rows_reversed):
                reversed_result = articles_query.list_project_sources(1)

        forward_keys = [group["key"] for group in forward["sources"]]
        reversed_keys = [group["key"] for group in reversed_result["sources"]]
        self.assertEqual(forward_keys, reversed_keys)

    def test_mixed_timezone_timestamps_do_not_crash_source_sorting(self):
        rows = [
            {"id": 1, "title": "naive", "url": "https://example.com/1", "source": "Example",
             "source_url": "https://example.com", "published_at": datetime(2026, 9, 18, 9, 0)},
            {"id": 2, "title": "aware", "url": "https://example.com/2", "source": "Example",
             "source_url": "https://example.com", "published_at": datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)},
        ]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.articles_query.db.fetch_all", return_value=rows), \
             patch("services.articles.articles_query.resolve_source_trust", return_value={}):
            result = articles_query.list_project_sources(1)
        self.assertEqual([item["id"] for item in result["sources"][0]["articles"]], [2, 1])

    def test_attaches_a_trust_tier_to_every_source_group_on_the_page(self):
        rows = [
            {"id": 1, "title": "A1", "url": "https://nytimes.com/a1", "source": "doc.pdf",
             "source_url": "document://project-document/9", "published_at": datetime(2024, 1, 3)},
        ]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.articles_query.db.fetch_all", return_value=rows), \
             patch("services.articles.articles_query.resolve_source_trust") as mock_resolve:
            mock_resolve.return_value = {"real:nytimes.com": {"tier": "trusted", "is_default": True}}
            result = articles_query.list_project_sources(1)

        # resolve_source_trust() is handed the actual page of groups, not the
        # raw rows - one call for the whole page, not one per group.
        mock_resolve.assert_called_once()
        (page_arg,), _ = mock_resolve.call_args
        self.assertEqual([g["key"] for g in page_arg], ["real:nytimes.com"])
        self.assertEqual(result["sources"][0]["trust"], {"tier": "trusted", "is_default": True})

    def test_no_sources_never_calls_resolve_source_trust(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.articles_query.db.fetch_all", return_value=[]), \
             patch("services.articles.articles_query.resolve_source_trust") as mock_resolve:
            result = articles_query.list_project_sources(1)
        self.assertEqual(result["sources"], [])
        mock_resolve.assert_not_called()


class ListProjectSourceKeysTests(unittest.TestCase):
    """list_project_source_keys() - the lighter, preview-free counterpart to
    list_project_sources() used to validate a trust-tier write (see
    source_trust.py) targets a source this project can actually see."""

    def test_falsy_project_id_returns_empty_without_querying(self):
        with patch("services.articles.articles_query.db.fetch_all") as mock_fetch_all:
            result = articles_query.list_project_source_keys(None)
        self.assertEqual(result, {})
        mock_fetch_all.assert_not_called()

    def test_no_articles_returns_empty_without_querying_articles_table(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.articles_query.list_article_ids_for_project", return_value=[]), \
             patch("services.articles.articles_query.db.fetch_all") as mock_fetch_all:
            result = articles_query.list_project_source_keys(1)
        self.assertEqual(result, {})
        mock_fetch_all.assert_not_called()

    def test_query_error_returns_empty_instead_of_raising(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.articles_query.list_article_ids_for_project", return_value=[1]), \
             patch("services.articles.articles_query.db.fetch_all", side_effect=RuntimeError("boom")):
            result = articles_query.list_project_source_keys(1)
        self.assertEqual(result, {})

    def test_matches_the_exact_keys_list_project_sources_would_group_under(self):
        rows = [
            {"url": "https://nytimes.com/a1", "source": "doc.pdf", "source_url": "document://project-document/9"},
            {"url": "document://project-document/1/article/3", "source": "report.pdf",
             "source_url": "document://project-document/1"},
        ]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.articles_query.list_article_ids_for_project", return_value=[1, 3]), \
             patch("services.articles.articles_query.db.fetch_all", return_value=rows):
            result = articles_query.list_project_source_keys(1)
        self.assertEqual(result, {
            "real:nytimes.com": {"type": "real", "label": "nytimes.com"},
            "document:document://project-document/1": {"type": "document", "label": "report.pdf"},
        })


class SourceTrustSummaryForRowsTests(unittest.TestCase):
    """source_trust_summary_for_rows() - the dashboard KPI's project-wide
    trust-tier aggregate, computed over already-fetched article rows rather
    than a fresh query (unlike list_project_sources(), which only resolves
    trust for one page of source groups)."""

    def test_no_rows_returns_zeroed_summary_without_resolving_trust(self):
        with patch("services.articles.articles_query.resolve_source_trust") as mock_resolve:
            result = articles_query.source_trust_summary_for_rows([])
        mock_resolve.assert_not_called()
        self.assertEqual(result["total_sources"], 0)
        self.assertEqual(result["total_articles"], 0)
        self.assertIsNone(result["trusted_pct"])
        self.assertEqual(result["tiers"]["trusted"], {"sources": 0, "articles": 0})

    def test_aggregates_article_and_source_counts_per_tier(self):
        rows = [
            {"url": "https://trusted.example/a1"},
            {"url": "https://trusted.example/a2"},
            {"url": "https://sketchy.example/a1"},
            {"url": None, "source": "doc.pdf", "source_url": "document://project-document/1"},
        ]

        def fake_resolve(sources, project_id=None):
            return {
                "real:trusted.example": {"tier": "trusted"},
                "real:sketchy.example": {"tier": "untrusted"},
                "document:document://project-document/1": {"tier": "unknown"},
            }

        with patch("services.articles.articles_query.resolve_source_trust", side_effect=fake_resolve):
            result = articles_query.source_trust_summary_for_rows(rows, project_id=7)

        self.assertEqual(result["total_sources"], 3)
        self.assertEqual(result["total_articles"], 4)
        self.assertEqual(result["tiers"]["trusted"], {"sources": 1, "articles": 2})
        self.assertEqual(result["tiers"]["untrusted"], {"sources": 1, "articles": 1})
        self.assertEqual(result["tiers"]["unknown"], {"sources": 1, "articles": 1})
        self.assertEqual(result["tiers"]["mixed"], {"sources": 0, "articles": 0})
        self.assertEqual(result["trusted_pct"], 50.0)

    def test_missing_tier_falls_back_to_unknown(self):
        rows = [{"url": "https://example.com/a"}]
        with patch("services.articles.articles_query.resolve_source_trust", return_value={}):
            result = articles_query.source_trust_summary_for_rows(rows)
        self.assertEqual(result["tiers"]["unknown"], {"sources": 1, "articles": 1})
        self.assertEqual(result["trusted_pct"], 0.0)


class ListArticleIdsForSourceHostTests(unittest.TestCase):
    """The query-side counterpart to ListProjectSourcesTests above - it must
    match every article that list_project_sources() would group/label under
    the same "real source" key, or the Articles page's source-host filter and
    the Sources tab's "View articles" link silently disagree."""

    def test_falsy_project_id_returns_empty_without_querying(self):
        with patch("services.articles.articles_query.db.fetch_all") as mock_fetch_all:
            result = articles_query.list_article_ids_for_source_host(None, "nytimes.com")
        self.assertEqual(result, [])
        mock_fetch_all.assert_not_called()

    def test_matches_articles_by_hostname_case_insensitively(self):
        rows = [
            {"id": 1, "url": "https://NYTimes.com/a1"},
            {"id": 2, "url": "https://example.com/a2"},
        ]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.articles_query.list_article_ids_for_project", return_value=[1, 2]), \
             patch("services.articles.articles_query.db.fetch_all", return_value=rows):
            result = articles_query.list_article_ids_for_source_host(1, "nytimes.com")
        self.assertEqual(result, [1])

    def test_excludes_document_sourced_articles(self):
        rows = [{"id": 1, "url": "document://project-document/9/article/1"}]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.articles_query.list_article_ids_for_project", return_value=[1]), \
             patch("services.articles.articles_query.db.fetch_all", return_value=rows):
            result = articles_query.list_article_ids_for_source_host(1, "project-document")
        self.assertEqual(result, [])

    def test_matches_the_exact_label_list_project_sources_would_show_for_a_schemeless_url(self):
        """A url with no scheme (e.g. hand-typed or JSONL-imported data) has no
        parseable hostname, so list_project_sources() falls back to the whole
        url as its grouping label/link - see _real_source_host(). This filter
        must recognize that exact same fallback label, or clicking "View
        articles" for such a source (or picking it from the Articles page's
        dropdown) always comes back with zero results despite the source
        having articles - the bug this test pins."""
        url = "example.com/press-release"
        rows = [{"id": 7, "url": url}]

        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.articles_query.db.fetch_all", return_value=rows), \
             patch("services.articles.articles_query.resolve_source_trust", return_value={}):
            sources = articles_query.list_project_sources(1)
        label = sources["sources"][0]["label"]
        self.assertEqual(label, url)

        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.articles_query.list_article_ids_for_project", return_value=[7]), \
             patch("services.articles.articles_query.db.fetch_all", return_value=rows):
            matches = articles_query.list_article_ids_for_source_host(1, label)
        self.assertEqual(matches, [7])

    def test_query_error_returns_empty_instead_of_raising(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"), \
             patch("services.articles.articles_query.list_article_ids_for_project", return_value=[1]), \
             patch("services.articles.articles_query.db.fetch_all", side_effect=RuntimeError("boom")):
            result = articles_query.list_article_ids_for_source_host(1, "nytimes.com")
        self.assertEqual(result, [])


class WherePartsSourceHostTests(unittest.TestCase):
    """source_host_ids lets a multi-page reader (articles_search's scan loop,
    articles_store.export_articles's bulk loop) resolve source_host once and
    reuse it, instead of paying list_article_ids_for_source_host's full
    project scan again on every page."""

    def test_precomputed_ids_are_used_without_recomputing(self):
        with patch("services.articles.articles_query.list_article_ids_for_project", return_value=[5, 9]), \
             patch("services.articles.articles_query.list_article_ids_for_source_host") as mock_resolve:
            where_sql, params = articles_query._where_parts(project_id=1, source_host="nytimes.com", source_host_ids=[5, 9])
        mock_resolve.assert_not_called()
        self.assertIn("id = any(%s)", where_sql)
        self.assertIn([5, 9], params)

    def test_empty_precomputed_ids_short_circuits_to_no_rows(self):
        with patch("services.articles.articles_query.list_article_ids_for_project", return_value=[5, 9]), \
             patch("services.articles.articles_query.list_article_ids_for_source_host") as mock_resolve:
            where_sql, _ = articles_query._where_parts(project_id=1, source_host="nytimes.com", source_host_ids=[])
        mock_resolve.assert_not_called()
        self.assertIn("id = -1", where_sql)

    def test_sentiment_filter_only_matches_assessed_values(self):
        where_sql, params = articles_query._where_parts(sentiment="neutral")
        self.assertIn("sentiment = %s", where_sql)
        self.assertIn("sentiment_status = 'ran'", where_sql)
        self.assertIn("neutral", params)

    def test_not_assessed_status_excludes_pending_and_failed_rows(self):
        where_sql, _ = articles_query._where_parts(status="not_assessed")
        self.assertIn("analysis_status = 'success'", where_sql)
        self.assertIn("skipped_model_unavailable", where_sql)

    def test_no_precomputed_ids_falls_back_to_resolving_from_source_host(self):
        with patch("services.articles.articles_query.list_article_ids_for_project", return_value=[5, 9]), \
             patch("services.articles.articles_query.list_article_ids_for_source_host", return_value=[3]) as mock_resolve:
            where_sql, params = articles_query._where_parts(project_id=1, source_host="nytimes.com")
        mock_resolve.assert_called_once_with(1, "nytimes.com")
        self.assertIn([3], params)


class GetAnalysisStatusCountsTests(unittest.TestCase):
    def test_no_database_configured_returns_empty(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", ""):
            self.assertEqual(articles_query.get_analysis_status_counts(), {})

    def test_scoped_to_project_joins_article_projects(self):
        rows = [{"analysis_status": "success", "total": 5}, {"analysis_status": "failed", "total": 2}]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=rows) as mock_fetch_all:
                result = articles_query.get_analysis_status_counts(project_id=1)
        self.assertEqual(result, {"success": 5, "failed": 2})
        args, _ = mock_fetch_all.call_args
        self.assertIn("article_projects", args[0])

    def test_unscoped_counts_all_articles(self):
        rows = [{"analysis_status": "success", "total": 10}]
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=rows) as mock_fetch_all:
                result = articles_query.get_analysis_status_counts()
        self.assertEqual(result, {"success": 10})
        args, _ = mock_fetch_all.call_args
        self.assertNotIn("article_projects", args[0])

    def test_query_error_returns_empty_instead_of_raising(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", side_effect=RuntimeError("boom")):
                self.assertEqual(articles_query.get_analysis_status_counts(), {})


class ListAnalysisErrorsTests(unittest.TestCase):
    def test_no_database_configured_returns_empty_page(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", ""):
            result = articles_query.list_analysis_errors()
        self.assertEqual(result, {"errors": [], "total": 0, "limit": 24, "offset": 0})

    def test_filters_to_failed_status(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[]) as mock_fetch_all:
                with patch("services.articles.articles_query.db.fetch_one", return_value={"total": 0}):
                    articles_query.list_analysis_errors()
        args, _ = mock_fetch_all.call_args
        self.assertIn("analysis_status = 'failed'", args[0])

    def test_project_scoping_adds_article_projects_filter(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[]) as mock_fetch_all:
                with patch("services.articles.articles_query.db.fetch_one", return_value={"total": 0}):
                    articles_query.list_analysis_errors(project_id=3)
        sql, params = mock_fetch_all.call_args.args
        self.assertIn("article_projects", sql)
        self.assertIn(3, params)

    def test_query_error_returns_empty_page(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", side_effect=RuntimeError("boom")):
                result = articles_query.list_analysis_errors()
        self.assertEqual(result["errors"], [])


class GetArticleAnalysisTests(unittest.TestCase):
    def setUp(self):
        articles_query._live_articles_columns.cache_clear()

    def tearDown(self):
        articles_query._live_articles_columns.cache_clear()

    def test_no_database_configured_returns_none(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", ""):
            self.assertIsNone(articles_query.get_article_analysis(1))

    def test_article_not_found_returns_none(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[]):
                with patch("services.articles.articles_query.db.fetch_one", return_value=None):
                    self.assertIsNone(articles_query.get_article_analysis(999))

    def test_shapes_a_successful_analysis(self):
        row = {
            "id": 1, "url": "https://example.com/a", "title": "EV Review", "source": "example.com",
            "published": "2026-01-01", "sentiment": "positive", "article_category": "review",
            "writer_tone": "enthusiastic", "article_tone": "positive",
            "insight_json": {"summary": "Great car."}, "analyzed_at": "2026-01-01T00:00:00Z",
            "analysis_model": "sentiment=fake", "analysis_prompt_version": "analysis-pipeline/1",
            "analysis_status": "success", "analysis_error": None,
            "sentiment_score": 0.9, "sentiment_low_confidence": False,
            "sentiment_model": "fake-sentiment-model",
        }
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[{"column_name": k} for k in row]):
                with patch("services.articles.articles_query.db.fetch_one", return_value=row):
                    result = articles_query.get_article_analysis(1)
        self.assertEqual(result["article_id"], 1)
        self.assertEqual(result["sentiment"], "positive")
        self.assertEqual(result["summary"], "Great car.")
        self.assertEqual(result["analysis_status"], "success")
        self.assertIsNone(result["analysis_error"])
        self.assertEqual(result["confidence"]["sentiment"], 0.9)
        self.assertFalse(result["confidence"]["sentiment_low_confidence"])
        self.assertEqual(result["models"]["sentiment"], "fake-sentiment-model")

    def test_malformed_insight_json_does_not_leak_through(self):
        row = {
            "id": 1, "url": "u", "title": "t", "source": "s", "published": None,
            "sentiment": "neutral", "article_category": "general_article",
            "writer_tone": "neutral", "article_tone": "neutral",
            "insight_json": "not a dict", "analyzed_at": None,
            "analysis_model": None, "analysis_prompt_version": None,
        }
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[]):
                with patch("services.articles.articles_query.db.fetch_one", return_value=row):
                    result = articles_query.get_article_analysis(1)
        self.assertEqual(result["insight_json"], {})
        self.assertEqual(result["summary"], "")

    def test_failed_status_and_low_confidence_are_clearly_represented(self):
        row = {
            "id": 1, "url": "u", "title": "t", "source": "s", "published": None,
            "sentiment": "neutral", "article_category": "general_article",
            "writer_tone": "neutral", "article_tone": "neutral",
            "insight_json": {}, "analyzed_at": None, "analysis_model": None, "analysis_prompt_version": None,
            "analysis_status": "failed", "analysis_error": "model_unavailable",
            "sentiment_score": 0.2, "sentiment_low_confidence": True,
        }
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[{"column_name": k} for k in row]):
                with patch("services.articles.articles_query.db.fetch_one", return_value=row):
                    result = articles_query.get_article_analysis(1)
        self.assertEqual(result["analysis_status"], "failed")
        self.assertEqual(result["analysis_error"], "model_unavailable")
        self.assertTrue(result["confidence"]["sentiment_low_confidence"])

    def test_query_error_returns_none(self):
        with patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"):
            with patch("services.articles.articles_query.db.fetch_all", return_value=[]):
                with patch("services.articles.articles_query.db.fetch_one", side_effect=RuntimeError("boom")):
                    self.assertIsNone(articles_query.get_article_analysis(1))


if __name__ == "__main__":
    unittest.main()
