import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from llm_client import LLMQuotaError
from services.competitors import competitor_analysis


class GenerateFindingTests(unittest.TestCase):
    """generate_finding()/generate_findings() do deferred
    `from services.competitors.business_profile_store import ...` /
    `from services.competitors.competitors_store import ...` imports inside
    the function body, not at module level - a bad import path there only
    breaks at call time, so these must actually invoke the functions (not
    just import the module) to catch it. Regression tests for a reorg that
    broke exactly this: the module-level import graph checked out fine while
    these deferred imports still pointed at pre-move module paths."""

    def test_generate_finding_returns_none_without_evidence(self):
        with patch("services.competitors.competitor_analysis.db.fetch_all", return_value=[]):
            result = competitor_analysis.generate_finding(
                {"name": "Us"}, {"id": 1, "project_id": 1, "name": "Them"}
            )
        self.assertIsNone(result)

    def test_generate_findings_reports_no_tracked_competitors(self):
        with patch(
            "services.competitors.business_profile_store.get_profile", return_value=None
        ), patch(
            "services.competitors.competitors_store.list_competitors", return_value=[]
        ):
            result = competitor_analysis.generate_findings(1)
        self.assertEqual(result["generated"], 0)
        self.assertIsNotNone(result["error"])

    def test_generate_findings_surfaces_llm_error_instead_of_false_success(self):
        """A provider failure (e.g. DeepSeek 402 insufficient balance) must not
        be reported the same way as "no evidence this period" - the caller
        needs to know the AI call itself failed, not that there was nothing
        to say."""
        competitor = {"id": 1, "project_id": 1, "name": "Them"}
        validation = {
            "scanned": 5, "linked": 0,
            "per_competitor": {1: {"valid": 1, "rejected": 0, "stories": 1}},
            "rejection_reasons": {}, "period_days": 30,
        }
        with patch(
            "services.competitors.business_profile_store.get_profile", return_value={"name": "Us"}
        ), patch(
            "services.competitors.competitors_store.list_competitors", return_value=[competitor]
        ), patch.object(
            competitor_analysis, "validate_competitor_articles", return_value=validation
        ), patch.object(
            competitor_analysis, "generate_finding",
            side_effect=LLMQuotaError("402 error for url: https://api.deepseek.com/v1/chat/completions - Insufficient Balance"),
        ):
            result = competitor_analysis.generate_findings(1)

        self.assertEqual(result["generated"], 0)
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["error_code"], "llm_quota_exceeded")


class EvidenceGateTests(unittest.TestCase):
    """The gates decide what the model is allowed to call evidence, so each one
    is tested against the shape of input that motivated it."""

    def test_generic_company_name_yields_no_aliases(self):
        """A competitor named "Stories" matched every article containing the
        word - drag racing, a Philly roundup, a fact check - and scored them at
        full title prominence. A name that is only a common word cannot be
        matched on text alone, so it produces no aliases and therefore no
        evidence."""
        self.assertEqual(competitor_analysis._aliases({"name": "Stories", "domain": "stories.com"}), [])
        self.assertEqual(
            competitor_analysis._aliases({"name": "Café Younes", "domain": "cafeyounes.com"}),
            ["Café Younes", "cafeyounes"],
        )

    def test_boilerplate_pages_are_recognized(self):
        for url, title in [
            ("https://cafeyounes.com/contact", "CONTACT US"),
            ("https://cafeyounes.com/pages/work-with-us", "Work with Us"),
            ("https://cafeyounes.com/x", "Locations & Menus"),
            ("https://cafeyounes.com/franchise", "FRANCHISE New"),
        ]:
            with self.subTest(url=url):
                self.assertTrue(competitor_analysis._is_boilerplate_page(url, title))

    def test_real_content_is_not_boilerplate(self):
        for url, title in [
            ("https://cafeyounes.com/products/copper-rakweh", "Copper Rakweh | Café Younes"),
            ("https://news.example.com/coffee-academy", "Coffee Academy"),
            ("https://waradana.com/best-coffee-houses", "Discover the Best Coffee Houses in Beirut"),
        ]:
            with self.subTest(url=url):
                self.assertFalse(competitor_analysis._is_boilerplate_page(url, title))

    def test_mention_prominence_is_scored_by_where_the_name_appears(self):
        aliases = ["Acme"]
        title_hit = competitor_analysis._mention_profile("Acme raises prices", "", "body", aliases)
        summary_hit = competitor_analysis._mention_profile("Coffee news", "Acme moved", "body", aliases)
        self.assertEqual(title_hit, ("Acme", 1.0))
        self.assertEqual(summary_hit, ("Acme", 0.7))

        # A lone mention buried late in a long roundup: present, but the piece
        # is not about them - this is the case the floor exists to drop.
        buried = "filler " * 400 + "Acme" + " filler" * 400
        _alias, score = competitor_analysis._mention_profile("Market roundup", "", buried, aliases)
        self.assertLess(score, competitor_analysis.MIN_MENTION_SCORE)

        # Repeated through the body, or introduced up front: kept.
        repeated = "filler " * 400 + ("Acme " * 3) + "filler " * 400
        _alias, score = competitor_analysis._mention_profile("Market roundup", "", repeated, aliases)
        self.assertGreaterEqual(score, competitor_analysis.MIN_MENTION_SCORE)

        leading = "Acme " + "filler " * 400
        _alias, score = competitor_analysis._mention_profile("Market roundup", "", leading, aliases)
        self.assertGreaterEqual(score, competitor_analysis.MIN_MENTION_SCORE)

    def test_whole_word_matching_still_holds(self):
        """Substring matching would let "Ford" match "Bradford"."""
        self.assertEqual(
            competitor_analysis._mention_profile("Bradford council news", "", "Bradford", ["Ford"]),
            (None, 0.0),
        )


class ValidateCompetitorArticlesTests(unittest.TestCase):
    def test_prunes_rows_for_articles_outside_the_window(self):
        """A row written by an earlier run against a wider window must not
        survive into a narrower one. Only in-window articles are scanned, and
        `_counts_for`/`_evidence_for` have no date bound, so a leftover 'valid'
        row would keep inflating the card's article_count and could still be
        served as evidence for a period it falls outside."""
        now = datetime.now(timezone.utc)
        in_window = {
            "id": 7,
            "url": "https://news.example.com/acme-pricing",
            "source": "news.example.com",
            "source_url": "https://news.example.com/feed.xml",
            "title": "Acme raises prices",
            "summary": "",
            "text": "Acme " + ("pricing detail " * 100),
            "story_id": 1,
            "published_at": now,
            "created_at": now,
        }
        stale = {**in_window, "id": 9, "story_id": 2,
                 "published_at": now - timedelta(days=200),
                 "created_at": now - timedelta(days=200)}

        cursor = MagicMock()
        transaction = MagicMock()
        transaction.__enter__.return_value = cursor
        transaction.__exit__.return_value = False

        with patch.object(competitor_analysis.db, "fetch_all", return_value=[in_window, stale]), \
             patch.object(competitor_analysis.db, "transaction", return_value=transaction):
            result = competitor_analysis.validate_competitor_articles(
                1, [{"id": 3, "name": "Acme"}], period_days=30
            )

        delete_sql, delete_params = cursor.execute.call_args[0]
        self.assertIn("delete from competitor_articles", delete_sql)
        # Only the in-window article is spared; the 200-day-old one is dropped
        # from the table rather than left behind as a 'valid' row.
        self.assertEqual(delete_params, ([3], [7]))
        self.assertEqual(result["per_competitor"][3]["valid"], 1)

    def test_prune_clears_everything_when_no_articles_are_in_window(self):
        """Zero in-window evidence has to mean zero, not "whatever the last
        run left behind"."""
        cursor = MagicMock()
        transaction = MagicMock()
        transaction.__enter__.return_value = cursor
        transaction.__exit__.return_value = False

        with patch.object(competitor_analysis.db, "fetch_all", return_value=[]), \
             patch.object(competitor_analysis.db, "transaction", return_value=transaction):
            result = competitor_analysis.validate_competitor_articles(
                1, [{"id": 3, "name": "Acme"}], period_days=30
            )

        _sql, delete_params = cursor.execute.call_args[0]
        self.assertEqual(delete_params, ([3], []))
        self.assertEqual(result["per_competitor"][3]["valid"], 0)


class AnalysisJobTests(unittest.TestCase):
    """Analysis runs as a background job now, so its terminal state is the only
    thing the user ever sees - every path has to reach one that carries the
    reason."""

    def _run(self, project_id, **patch_kwargs):
        with patch.object(competitor_analysis, "generate_findings", **patch_kwargs) as generate:
            run_id = competitor_analysis.create_analysis_run(project_id)
            competitor_analysis.run_analysis_job(run_id, project_id, 30, False)
        return competitor_analysis.get_analysis_run(run_id), generate

    def test_successful_job_records_counts_and_gets_a_logger(self):
        run, generate = self._run(11, return_value={
            "generated": 2, "skipped": [], "validation": {"scanned": 5}, "error": None,
        })
        self.assertEqual(run["status"], "success")
        self.assertEqual(run["generated"], 2)
        # The job must hand generate_findings a real logger - that callback is
        # the only reason the user sees anything before the run ends.
        self.assertTrue(callable(generate.call_args.kwargs["log"]))

    def test_provider_failure_is_a_failed_run_not_zero_reports(self):
        """Same distinction generate_findings itself draws: a quota/outage error
        must not surface as "nothing needed reporting"."""
        run, _ = self._run(12, return_value={
            "generated": 0, "skipped": [], "validation": {},
            "error": "Insufficient balance", "error_code": "llm_quota_exceeded",
        })
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error_code"], "llm_quota_exceeded")

    def test_unexpected_exception_becomes_a_failed_run_with_a_reason(self):
        """The job runs after the response is sent, so an exception raised here
        would otherwise reach nothing but the server log."""
        run, _ = self._run(13, side_effect=RuntimeError("scrape exploded"))
        self.assertEqual(run["status"], "failed")
        self.assertIn("scrape exploded", run["error"])
        self.assertIn("scrape exploded", " ".join(entry["message"] for entry in run["logs"]))

    def test_run_is_scoped_to_its_project(self):
        run_id = competitor_analysis.create_analysis_run(14)
        self.assertEqual(competitor_analysis.get_analysis_run(run_id)["project_id"], 14)
        self.assertEqual(competitor_analysis.get_active_analysis_run(14)["run_id"], run_id)
        self.assertIsNone(competitor_analysis.get_active_analysis_run(9999))


if __name__ == "__main__":
    unittest.main()
