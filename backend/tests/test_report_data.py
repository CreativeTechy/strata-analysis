"""services/reports/report_data.py: the single snapshot the Export Summary
PDF and its "variation from last run" section are both built from."""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.reports import report_data


def _row(id_, status="success", sentiment="positive", relevance=None, published=None, summary="s"):
    return {
        "id": id_, "analysis_status": status, "sentiment": sentiment,
        "relevance_score": relevance, "published": published, "created_at": published,
        "title": f"Article {id_}", "summary": summary, "source": "doc.pdf", "url": f"https://x/{id_}",
        "topics": [], "key_points": [], "insight_json": {},
    }


class StatusCountsTests(unittest.TestCase):
    def test_counts_every_status_bucket(self):
        rows = [_row(1, "success"), _row(2, "pending"), _row(3, "processing"), _row(4, "failed"), _row(5, "partial")]
        counts = report_data._status_counts(rows)
        self.assertEqual(counts, {"total": 5, "analyzed": 1, "pending": 1, "processing": 1, "failed": 1, "partial": 1})

    def test_empty_scope(self):
        self.assertEqual(report_data._status_counts([]), {"total": 0, "analyzed": 0, "pending": 0, "processing": 0, "failed": 0, "partial": 0})


class SentimentBreakdownTests(unittest.TestCase):
    def test_percentages_and_net_sentiment_over_successful_rows_only(self):
        """Caller contract: only ever pass analysis_status=='success' rows -
        this only asserts the arithmetic, the exclusion itself is asserted in
        BuildReportDataTests below."""
        rows = [_row(1, sentiment="positive"), _row(2, sentiment="positive"), _row(3, sentiment="negative"), _row(4, sentiment="neutral")]
        breakdown = report_data._sentiment_breakdown(rows)
        self.assertEqual(breakdown["positive"], {"count": 2, "pct": 50.0})
        self.assertEqual(breakdown["negative"], {"count": 1, "pct": 25.0})
        self.assertEqual(breakdown["neutral"], {"count": 1, "pct": 25.0})
        self.assertEqual(breakdown["mixed"], {"count": 0, "pct": 0.0})
        self.assertEqual(breakdown["analyzed_total"], 4)
        self.assertEqual(breakdown["net_sentiment"], 25)  # (2-1)/4 * 100

    def test_no_analyzed_rows_is_all_zero_not_a_division_error(self):
        breakdown = report_data._sentiment_breakdown([])
        self.assertEqual(breakdown["analyzed_total"], 0)
        self.assertEqual(breakdown["positive"], {"count": 0, "pct": 0.0})
        self.assertEqual(breakdown["net_sentiment"], 0)


class TopArticlesTests(unittest.TestCase):
    def test_ranks_by_relevance_score_descending(self):
        rows = [_row(1, relevance=0.2), _row(2, relevance=0.9), _row(3, relevance=0.5)]
        top, fallback = report_data._top_articles(rows, limit=10)
        self.assertEqual([a["article_id"] for a in top], [2, 3, 1])
        self.assertFalse(fallback)
        self.assertTrue(all(a["ranking_method"] == "relevance_score" for a in top))

    def test_deterministic_tie_break_by_published_then_id(self):
        older = datetime(2026, 1, 1, tzinfo=timezone.utc)
        newer = datetime(2026, 2, 1, tzinfo=timezone.utc)
        rows = [
            _row(1, relevance=0.5, published=older),
            _row(2, relevance=0.5, published=newer),
            _row(3, relevance=0.5, published=newer),
        ]
        top, _ = report_data._top_articles(rows, limit=10)
        # Same score -> newer published wins; same score+date -> higher id wins.
        self.assertEqual([a["article_id"] for a in top], [3, 2, 1])

    def test_falls_back_to_recency_when_every_score_is_missing(self):
        older = datetime(2026, 1, 1, tzinfo=timezone.utc)
        newer = datetime(2026, 2, 1, tzinfo=timezone.utc)
        rows = [_row(1, relevance=None, published=older), _row(2, relevance=None, published=newer)]
        top, fallback = report_data._top_articles(rows, limit=10)
        self.assertTrue(fallback)
        self.assertEqual([a["article_id"] for a in top], [2, 1])
        self.assertTrue(all(a["ranking_method"] == "fallback_recency" for a in top))

    def test_partial_scores_do_not_trigger_the_fallback(self):
        """Only a *complete* absence of relevance_score across every
        candidate means "this project's pipeline never populated it" -
        one article missing a score just ranks last among real scores."""
        rows = [_row(1, relevance=0.8), _row(2, relevance=None)]
        top, fallback = report_data._top_articles(rows, limit=10)
        self.assertFalse(fallback)
        self.assertEqual([a["article_id"] for a in top], [1, 2])

    def test_returns_fewer_than_the_limit_when_fewer_eligible_articles_exist(self):
        rows = [_row(1, relevance=0.5), _row(2, relevance=0.6)]
        top, _ = report_data._top_articles(rows, limit=10)
        self.assertEqual(len(top), 2)

    def test_empty_scope_returns_empty_without_fallback_flag(self):
        top, fallback = report_data._top_articles([], limit=10)
        self.assertEqual(top, [])
        self.assertFalse(fallback)

    def test_limit_is_respected(self):
        rows = [_row(i, relevance=float(i)) for i in range(15)]
        top, _ = report_data._top_articles(rows, limit=10)
        self.assertEqual(len(top), 10)
        self.assertEqual(top[0]["article_id"], 14)


class SourceLabelTests(unittest.TestCase):
    def test_prefers_the_document_filename(self):
        self.assertEqual(report_data._source_label({"source": "report.pdf", "url": "https://elsewhere.com/a"}), "report.pdf")

    def test_falls_back_to_url_host_without_a_document(self):
        self.assertEqual(report_data._source_label({"source": "", "url": "https://www.example.com/a", "source_url": ""}), "example.com")

    def test_ignores_the_synthetic_document_url_scheme(self):
        self.assertEqual(
            report_data._source_label({"source": "", "url": "document://project-document/9", "source_url": ""}),
            "Unknown source",
        )


class ExecutiveSummaryFreshnessTests(unittest.TestCase):
    def test_uncached_result_is_never_considered_stale(self):
        self.assertFalse(report_data._stale_executive_summary({"cached": False, "generated_at": None}, []))
        self.assertFalse(report_data._stale_executive_summary(None, []))

    def test_missing_generated_at_on_a_cached_row_is_treated_as_stale(self):
        self.assertTrue(report_data._stale_executive_summary({"cached": True, "generated_at": None}, [_row(1)]))

    def test_stale_when_an_article_was_analyzed_after_the_cache_was_written(self):
        cached = {"cached": True, "generated_at": "2026-03-01T00:00:00+00:00"}
        rows = [_row(1, published=datetime(2026, 3, 2, tzinfo=timezone.utc))]
        self.assertTrue(report_data._stale_executive_summary(cached, rows))

    def test_fresh_when_nothing_in_scope_postdates_the_cache(self):
        cached = {"cached": True, "generated_at": "2026-03-05T00:00:00+00:00"}
        rows = [_row(1, published=datetime(2026, 3, 1, tzinfo=timezone.utc))]
        self.assertFalse(report_data._stale_executive_summary(cached, rows))


class _NoDbLookups(unittest.TestCase):
    """build_report_data's trust-tier and idea-comparison lookups hit the
    database; the build tests below are about counts/summary wiring, so
    stub both out (they have their own tests further down)."""

    def setUp(self):
        for name, value in (("_source_tiers", {}), ("_idea_comparisons", {"items": [], "error": None, "project_wide": True})):
            patcher = patch.object(report_data, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)


class BuildReportDataTests(_NoDbLookups):
    """Wires the pieces together for the period-scope path; run-scope is
    exercised in test_yesterday_comparison.py's scope-anchoring tests."""

    def test_sentiment_excludes_pending_and_failed_placeholder_rows(self):
        project = {"id": 1, "name": "Acme"}
        rows = [
            _row(1, status="success", sentiment="positive"),
            _row(2, status="pending", sentiment="neutral"),  # DEFAULT_ENRICHMENT placeholder
            _row(3, status="failed", sentiment="neutral"),
        ]
        with patch.object(report_data, "_fetch_period_rows", return_value=rows), \
             patch.object(report_data, "generate_trend_summary", return_value={"summary": "ok", "cached": False}):
            data = report_data.build_report_data(project, period="all", run=None)

        self.assertEqual(data["counts"], {"total": 3, "analyzed": 1, "pending": 1, "processing": 0, "failed": 1, "partial": 0})
        self.assertEqual(data["sentiment"]["analyzed_total"], 1)
        self.assertEqual(data["sentiment"]["positive"]["count"], 1)

    def test_fewer_than_ten_analyzed_articles_yields_a_shorter_top_list(self):
        project = {"id": 1, "name": "Acme"}
        rows = [_row(i, status="success", relevance=float(i)) for i in range(3)]
        with patch.object(report_data, "_fetch_period_rows", return_value=rows), \
             patch.object(report_data, "generate_trend_summary", return_value={"summary": "ok", "cached": False}):
            data = report_data.build_report_data(project, period="all", run=None)
        self.assertEqual(len(data["top_articles"]), 3)

    def test_regenerates_the_executive_summary_when_stale(self):
        project = {"id": 1, "name": "Acme"}
        rows = [_row(1, status="success", published=datetime(2026, 3, 5, tzinfo=timezone.utc))]
        stale_cache = {"summary": "old", "cached": True, "generated_at": "2026-01-01T00:00:00+00:00"}
        fresh_cache = {"summary": "new", "cached": False}
        with patch.object(report_data, "_fetch_period_rows", return_value=rows), \
             patch.object(report_data, "generate_trend_summary", side_effect=[stale_cache, fresh_cache]) as gen:
            data = report_data.build_report_data(project, period="all", run=None)
        self.assertEqual(data["executive_summary"]["text"], "new")
        self.assertEqual(gen.call_count, 2)
        self.assertTrue(gen.call_args_list[1].kwargs.get("force"))


class ExecutiveSummaryLlmFailureTests(_NoDbLookups):
    """generate_trend_summary() calls the configured LLM with no internal
    error handling of its own - build_report_data() must not let that
    failure escape and take down the whole PDF export the way an unguarded
    call used to (main.py's /trend-summary route already handles this exact
    failure for the on-screen summary; this mirrors it)."""

    def test_llm_failure_degrades_the_executive_summary_instead_of_raising(self):
        from llm_client import LLMError
        project = {"id": 1, "name": "Acme"}
        rows = [_row(1, status="success", published=datetime(2026, 3, 5, tzinfo=timezone.utc))]
        with patch.object(report_data, "_fetch_period_rows", return_value=rows), \
             patch.object(report_data, "generate_trend_summary",
                          side_effect=LLMError("down", code="llm_connection_error")):
            data = report_data.build_report_data(project, period="all", run=None)
        self.assertIsNone(data["executive_summary"]["text"])
        self.assertIsNotNone(data["executive_summary"]["error"])
        # The rest of the report must still be fully built despite the LLM outage.
        self.assertEqual(data["counts"]["total"], 1)
        self.assertEqual(data["sentiment"]["analyzed_total"], 1)

    def test_unexpected_exception_also_degrades_instead_of_raising(self):
        project = {"id": 1, "name": "Acme"}
        rows = [_row(1, status="success", published=datetime(2026, 3, 5, tzinfo=timezone.utc))]
        with patch.object(report_data, "_fetch_period_rows", return_value=rows), \
             patch.object(report_data, "generate_trend_summary", side_effect=RuntimeError("boom")):
            data = report_data.build_report_data(project, period="all", run=None)
        self.assertIsNone(data["executive_summary"]["text"])
        self.assertEqual(data["executive_summary"]["error"], "Something went wrong while generating the executive summary.")

    def test_forced_refresh_failure_keeps_the_stale_but_real_summary(self):
        """A stale-but-real paragraph is still more useful than none at all -
        don't discard it just because the forced refresh itself hit the same
        outage that made it stale-worth-refreshing in the first place."""
        from llm_client import LLMError
        project = {"id": 1, "name": "Acme"}
        rows = [_row(1, status="success", published=datetime(2026, 3, 5, tzinfo=timezone.utc))]
        stale_cache = {"summary": "old but real", "cached": True, "generated_at": "2026-01-01T00:00:00+00:00"}
        with patch.object(report_data, "_fetch_period_rows", return_value=rows), \
             patch.object(report_data, "generate_trend_summary",
                          side_effect=[stale_cache, LLMError("down", code="llm_connection_error")]):
            data = report_data.build_report_data(project, period="all", run=None)
        self.assertEqual(data["executive_summary"]["text"], "old but real")


class SourceTiersTests(unittest.TestCase):
    def test_resolves_one_tier_per_article_via_the_sources_tab_grouping_key(self):
        rows = [
            {"id": 1, "url": "https://www.bbc.co.uk/a", "source": None, "source_url": None},
            {"id": 2, "url": "https://www.bbc.co.uk/b", "source": None, "source_url": None},
            {"id": 3, "url": "document://project-document/7/article/9", "source": "file.pdf",
             "source_url": "document://project-document/7"},
        ]
        resolved = {
            "real:www.bbc.co.uk": {"tier": "trusted", "reason": "secret engagement note", "is_default": False},
            "document:document://project-document/7": {"tier": "unknown", "is_default": True},
        }
        with patch.object(report_data.source_trust, "resolve_many", return_value=resolved) as resolve:
            tiers = report_data._source_tiers(5, rows)
        # Grouped once per source, not once per article.
        self.assertEqual(len(resolve.call_args.args[0]), 2)
        self.assertEqual(resolve.call_args.kwargs["project_id"], 5)
        self.assertEqual(tiers[1], {"tier": "trusted", "is_default": False})
        self.assertEqual(tiers[2], {"tier": "trusted", "is_default": False})
        self.assertEqual(tiers[3], {"tier": "unknown", "is_default": True})
        # The override's free-text reason never reaches the report.
        self.assertNotIn("reason", tiers[1])

    def test_lookup_failure_falls_back_to_unknown(self):
        rows = [{"id": 1, "url": "https://x.com/a", "source": None, "source_url": None}]
        with patch.object(report_data.source_trust, "resolve_many", side_effect=RuntimeError("db down")):
            tiers = report_data._source_tiers(1, rows)
        self.assertEqual(tiers[1], {"tier": "unknown", "is_default": True})


class IdeaComparisonsTests(unittest.TestCase):
    COMPARISON = {
        "idea": "Petrol price", "type": "claim", "diverges": True, "summary": "They disagree.",
        "sources": [
            {"source_label": "eia.gov", "value": "$98", "article_id": 1, "title": "EIA"},
            {"source_label": "project-document", "value": "", "article_id": 2, "title": "Memo"},
        ],
    }
    IDENTITIES = {
        1: {"id": 1, "url": "https://eia.gov/a", "source": None, "source_url": None},
        2: {"id": 2, "url": "document://project-document/3/article/4", "source": "memo.pdf",
            "source_url": "document://project-document/3"},
    }

    def _build(self, run_id=None, attempted=True, list_side_effect=None):
        tiers = {1: {"tier": "trusted", "is_default": True}}
        with patch.object(report_data, "list_idea_comparisons",
                          side_effect=list_side_effect or (lambda *a, **k: [self.COMPARISON])) as listed,              patch.object(report_data, "has_run_generation_attempt", return_value=attempted),              patch.object(report_data, "generate_idea_comparisons") as generate,              patch.object(report_data, "_fetch_article_identities", return_value=self.IDENTITIES),              patch.object(report_data, "_source_tiers", return_value=tiers):
            section = report_data._idea_comparisons(1, run_id)
        return section, generate, listed

    def test_each_source_value_becomes_a_claim_with_its_trust_tier(self):
        section, generate, _ = self._build()
        generate.assert_not_called()  # project-wide scope never spends an LLM call on export
        self.assertTrue(section["project_wide"])
        self.assertIsNone(section["error"])
        item = section["items"][0]
        self.assertTrue(item["diverges"])
        first, second = item["claims"]
        self.assertEqual(first["source"], "eia.gov")
        self.assertEqual(first["claim"], "$98")
        self.assertEqual(first["source_tier"], {"tier": "trusted", "is_default": True})
        self.assertEqual(first["reference"], "/articles/1")
        # Document article labeled by its filename, like Top Articles - not "project-document".
        self.assertEqual(second["source"], "memo.pdf")
        self.assertIsNone(second["claim"])
        self.assertEqual(second["source_tier"], {"tier": "unknown", "is_default": True})

    def test_run_scope_generates_lazily_on_first_request_only(self):
        _, generate, _ = self._build(run_id="run-1", attempted=False)
        generate.assert_called_once_with(1, run_id="run-1")
        _, generate, _ = self._build(run_id="run-1", attempted=True)
        generate.assert_not_called()

    def test_llm_failure_keeps_cached_comparisons_and_discloses_the_error(self):
        from llm_client import LLMError
        with patch.object(report_data, "list_idea_comparisons", return_value=[self.COMPARISON]),              patch.object(report_data, "has_run_generation_attempt", return_value=False),              patch.object(report_data, "generate_idea_comparisons",
                          side_effect=LLMError("down", code="llm_connection_error")),              patch.object(report_data, "_fetch_article_identities", return_value=self.IDENTITIES),              patch.object(report_data, "_source_tiers", return_value={}):
            section = report_data._idea_comparisons(1, "run-1")
        self.assertIsNotNone(section["error"])
        self.assertEqual(len(section["items"]), 1)
        self.assertFalse(section["project_wide"])


if __name__ == "__main__":
    unittest.main()
