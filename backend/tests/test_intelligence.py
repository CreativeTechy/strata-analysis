import unittest
from collections import Counter
from datetime import datetime, timezone
from unittest.mock import patch

from services.intelligence import intelligence
from services.intelligence.intelligence import (
    classify_platform,
    count_configured_terms,
    emotion_signature,
    filter_rows_for_period,
    get_project_intelligence,
    keyword_existence_over_time,
    net_sentiment,
    pipeline_discovery_series,
    sentiment_by_run_series,
)


class IntelligenceHelpersTests(unittest.TestCase):
    def test_dashboard_history_requires_saved_analysis_results(self):
        with patch.object(intelligence, "_database_ready", return_value=True), \
             patch("db.fetch_all", return_value=[]) as fetch:
            intelligence._fetch_pipeline_runs(3)
        self.assertIn("exists (select 1 from article_analyses", fetch.call_args.args[0])

    def test_net_sentiment_is_positive_percentage_minus_negative_percentage(self):
        self.assertEqual(net_sentiment(Counter(positive=58, negative=15, neutral=27), 100), 43)
        self.assertEqual(net_sentiment(Counter(), 0), 0)

    def test_platform_classification_uses_x_hosts(self):
        self.assertEqual(classify_platform({"url": "https://x.com/strata/status/1"}), "X")
        self.assertEqual(classify_platform({"source_url": "https://twitter.com/strata"}), "X")
        self.assertEqual(classify_platform({"url": "https://example.com/story"}), "Web")

    def test_platform_classification_uses_reddit_and_telegram_hosts(self):
        self.assertEqual(classify_platform({"url": "https://www.reddit.com/r/test/comments/1/x/"}), "Reddit")
        self.assertEqual(classify_platform({"source": "reddit.com/r/test"}), "Reddit")
        self.assertEqual(classify_platform({"url": "https://t.me/somechannel/1"}), "Telegram")
        self.assertEqual(classify_platform({"source": "t.me/somechannel"}), "Telegram")

    def test_platform_classification_uses_new_social_hosts(self):
        cases = {
            "https://www.linkedin.com/posts/example": "LinkedIn",
            "https://threads.net/@example/post/1": "Threads",
            "https://m.facebook.com/example/posts/1": "Facebook",
            "https://www.instagram.com/p/example/": "Instagram",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(classify_platform({"url": url}), expected)

    def test_platform_classification_does_not_match_misleading_domains(self):
        self.assertEqual(classify_platform({"url": "https://instagram.com.example.test/post"}), "Web")
        self.assertEqual(classify_platform({"url": "https://notlinkedin.com/post"}), "Web")

    def test_malformed_collection_url_falls_through_to_article_url(self):
        row = {
            "url": "https://www.facebook.com/example/posts/1",
            "source_provenance": {"collection_source_url": "https://[broken"},
        }
        self.assertEqual(classify_platform(row), "Facebook")

    def test_explicit_collection_platform_wins_over_url(self):
        row = {
            "url": "https://example.com/post",
            "source_provenance": {"collection_platform": "threads"},
        }
        self.assertEqual(classify_platform(row), "Threads")

    def test_scraper_collection_source_url_wins_over_external_article_url(self):
        row = {
            "url": "https://publisher.example/article",
            "source_url": "document://project-document/2",
            "source_provenance": {
                "collection_source_url": "https://www.facebook.com/example/posts/1",
            },
        }
        self.assertEqual(classify_platform(row), "Facebook")

    def test_scraper_platform_aliases_are_normalized(self):
        self.assertEqual(classify_platform({"collection_platform": "tweet"}), "X")
        self.assertEqual(classify_platform({"collection_platform": "rss"}), "Web")

    def test_emotions_are_mapped_from_existing_tones(self):
        signature = {item["axis"]: item["count"] for item in emotion_signature([
            {"article_tone": "optimistic", "writer_tone": "neutral"},
            {"article_tone": "angry", "writer_tone": "neutral"},
            {"article_tone": "positive", "writer_tone": "neutral"},
        ])}
        self.assertEqual(signature["anticipation"], 1)
        self.assertEqual(signature["anger"], 1)
        self.assertEqual(signature["joy"], 1)

    def test_configured_terms_count_case_insensitive_occurrences(self):
        terms = count_configured_terms(
            [{"title": "Launch #Strata", "summary": "", "text": "Strata is here. #strata"}],
            hashtags=["Strata"],
            keywords=["launch"],
        )
        self.assertEqual({item["term"]: item["mentions"] for item in terms}, {"#Strata": 3, "launch": 1})

    def test_pipeline_deltas_cover_first_and_zero_baseline_runs(self):
        values = pipeline_discovery_series([
            {"id": "a", "sequence_number": 1, "articles_analyzed": 0},
            {"id": "b", "sequence_number": 2, "articles_analyzed": 10},
            {"id": "c", "sequence_number": 3, "articles_analyzed": 5},
        ])
        self.assertIsNone(values[0]["change_pct"])
        self.assertEqual(values[1]["change_pct"], 100)
        self.assertEqual(values[2]["change_pct"], -50)
        self.assertEqual([v["sequence_number"] for v in values], [1, 2, 3])

    def test_sentiment_by_run_pairs_each_run_with_its_own_counts(self):
        points = sentiment_by_run_series(
            [
                {"id": "a", "sequence_number": 1, "finished_at": "2026-07-01T00:00:00Z"},
                {"id": "b", "sequence_number": 2, "finished_at": "2026-07-02T00:00:00Z"},
            ],
            {"a": {"positive": 3, "negative": 1}},
        )
        self.assertEqual(points[0], {
            "run_id": "a", "sequence_number": 1, "completed_at": "2026-07-01T00:00:00Z", "total": 4,
            "net_sentiment": 50, "positive": 3, "negative": 1, "neutral": 0, "mixed": 0,
        })
        self.assertEqual(points[1], {
            "run_id": "b", "sequence_number": 2, "completed_at": "2026-07-02T00:00:00Z", "total": 0,
            "net_sentiment": 0, "positive": 0, "negative": 0, "neutral": 0, "mixed": 0,
        })

    def test_sentiment_by_run_defaults_sequence_number_to_none_when_missing(self):
        points = sentiment_by_run_series([{"id": "a", "finished_at": "2026-07-01T00:00:00Z"}], {})
        self.assertIsNone(points[0]["sequence_number"])

    def test_period_filter_uses_article_date(self):
        now = datetime(2026, 7, 23, tzinfo=timezone.utc)
        rows = [
            {"published": "2026-07-22T12:00:00Z"},
            {"published": "2026-06-01T12:00:00Z"},
        ]
        self.assertEqual(len(filter_rows_for_period(rows, "7d", now)), 1)

    def test_keyword_existence_splits_into_one_series_per_keyword(self):
        rows = [
            {"published": "2026-07-20T00:00:00Z", "title": "EV recall", "summary": "", "text": ""},
            {"published": "2026-07-20T00:00:00Z", "title": "battery fire", "summary": "", "text": ""},
            {"published": "2026-07-21T00:00:00Z", "title": "no matches here", "summary": "", "text": ""},
        ]
        series = keyword_existence_over_time(rows, ["EV", "battery"], all_keywords=True)
        self.assertEqual(
            series,
            [
                {"date": "2026-07-20", "EV": 1, "battery": 1},
                {"date": "2026-07-21", "EV": 0, "battery": 0},
            ],
        )

    def test_keyword_existence_combines_keywords_without_double_counting(self):
        rows = [
            {"published": "2026-07-20T00:00:00Z", "title": "EV battery recall", "summary": "", "text": ""},
            {"published": "2026-07-20T00:00:00Z", "title": "battery only", "summary": "", "text": ""},
        ]
        series = keyword_existence_over_time(rows, ["EV", "battery"], all_keywords=False)
        self.assertEqual(series, [{"date": "2026-07-20", "matches": 2}])

    def test_keyword_existence_filters_by_source_url(self):
        rows = [
            {"published": "2026-07-20T00:00:00Z", "source_url": "https://a.example.com", "title": "EV news", "summary": "", "text": ""},
            {"published": "2026-07-20T00:00:00Z", "source_url": "https://b.example.com", "title": "EV news too", "summary": "", "text": ""},
        ]
        series = keyword_existence_over_time(rows, ["EV"], source_url="https://a.example.com", all_keywords=False)
        self.assertEqual(series, [{"date": "2026-07-20", "matches": 1}])

    def test_keyword_existence_returns_empty_without_keywords(self):
        self.assertEqual(keyword_existence_over_time([{"title": "EV"}], []), [])


class ClassifyPlatformTests(unittest.TestCase):
    """Articles split out of an uploaded document carry a synthetic
    `document://` url; grouping them under "Web" alongside imported pages made
    the platform breakdown claim a provenance they don't have."""

    def test_document_articles_are_their_own_platform(self):
        self.assertEqual(
            intelligence.classify_platform({"url": "document://project-document/3/article/7"}),
            "Documents",
        )

    def test_imported_articles_still_classify_by_host(self):
        self.assertEqual(intelligence.classify_platform({"url": "https://x.com/someone/status/1"}), "X")
        self.assertEqual(intelligence.classify_platform({"url": "https://news.example.com/a"}), "Web")


class GetProjectIntelligenceTests(unittest.TestCase):
    """get_project_intelligence() does a deferred `from
    services.articles.articles_analytics import _topic_summary` import inside
    the function body, not at module level - a bad import path there only
    breaks at call time, so this must actually invoke the function (not just
    import the module) to catch it. Regression test for a reorg that broke
    exactly this: the module-level import graph checked out fine while this
    deferred import still pointed at the pre-move module path."""

    def test_runs_end_to_end_without_a_database(self):
        with patch.object(intelligence, "_database_ready", return_value=False):
            result = get_project_intelligence({"id": 1, "hashtags": [], "keywords": []})
        self.assertEqual(result["project_id"], 1)
        self.assertEqual(result["period"], "30d")
        self.assertIsNone(result["run_id"])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["document_count"], 0)
        self.assertIn("insights", result)
        self.assertEqual(result["coverage"], {
            "documents": 0, "documents_in_progress": 0, "articles": 0,
            "analyzed": 0, "pending": 0, "failed": 0, "active_run": None,
        })

    def test_coverage_groups_analysis_statuses_and_reports_the_active_run(self):
        """The dashboard's empty states key off these project-wide counts, so
        pending/processing both read as "waiting", partial counts as analyzed,
        and failed stays separate from pending."""
        counts = {"success": 4, "partial": 1, "pending": 3, "processing": 2, "failed": 1}
        active = {"id": "run-9", "status": "running", "articles_selected": 5, "articles_analyzed": 2, "stage": "analyze"}
        with patch.object(intelligence, "_database_ready", return_value=True), \
             patch("services.articles.articles_query.get_analysis_status_counts", return_value=counts), \
             patch("services.pipeline.pipeline_runs.get_active_run_for_project", return_value=active), \
             patch.object(intelligence, "_fetch_documents_in_progress", return_value=1):
            coverage = intelligence._fetch_coverage({"id": 7}, document_count=3)
        self.assertEqual(coverage, {
            "documents": 3, "documents_in_progress": 1, "articles": 11,
            "analyzed": 5, "pending": 5, "failed": 1,
            "active_run": {"id": "run-9", "status": "running", "articles_selected": 5, "articles_analyzed": 2},
        })

    def test_document_counts_read_the_competitor_table_for_a_competitor_study(self):
        with patch.object(intelligence, "_database_ready", return_value=True), \
             patch("db.fetch_one", return_value={"total": 2}) as fetch:
            self.assertEqual(intelligence._fetch_document_count(5, "competitor"), 2)
            self.assertIn("from competitor_documents", fetch.call_args.args[0])
            self.assertEqual(intelligence._fetch_documents_in_progress(5, "competitor"), 2)
            self.assertIn("from competitor_documents", fetch.call_args.args[0])
            intelligence._fetch_document_count(5)
            self.assertIn("from project_documents", fetch.call_args.args[0])

    def test_run_id_passes_through_into_the_response(self):
        """When a specific analysis run is selected, the response should echo
        it back so the frontend can confirm which run it's looking at."""
        with patch.object(intelligence, "_database_ready", return_value=False):
            result = get_project_intelligence({"id": 1, "hashtags": [], "keywords": []}, run_id="run-123")
        self.assertEqual(result["run_id"], "run-123")
        self.assertEqual(result["total"], 0)

    def test_platform_totals_include_every_supported_social_platform(self):
        rows = [
            {"url": "https://example.com/a", "sentiment": "neutral"},
            {"url": "https://x.com/a/status/1", "sentiment": "positive"},
            {"url": "https://reddit.com/r/a/comments/1", "sentiment": "negative"},
            {"url": "https://t.me/a/1", "sentiment": "neutral"},
            {"url": "https://linkedin.com/posts/a", "sentiment": "mixed"},
            {"url": "https://threads.net/@a/post/1", "sentiment": "positive"},
            {"url": "https://facebook.com/a/posts/1", "sentiment": "neutral"},
            {"url": "https://instagram.com/p/a", "sentiment": "positive"},
        ]
        with patch.object(intelligence, "_fetch_project_rows", return_value=rows), \
             patch.object(intelligence, "_fetch_pipeline_runs", return_value=[]), \
             patch.object(intelligence, "_fetch_document_count", return_value=0), \
             patch("services.articles.articles_query.resolve_source_trust", return_value={}):
            result = get_project_intelligence(
                {"id": 1, "hashtags": [], "keywords": []}, period="all"
            )
        totals = {item["platform"]: item["total"] for item in result["platforms"]}
        self.assertEqual(sum(totals.values()), result["total"])
        for platform in (
            "Web", "X", "Reddit", "Telegram", "LinkedIn", "Threads", "Facebook", "Instagram",
        ):
            self.assertEqual(totals[platform], 1)

    def test_malformed_collection_url_does_not_break_current_or_run_intelligence(self):
        rows = [{
            "url": "https://publisher.example/article",
            "sentiment": "neutral",
            "source_provenance": {"collection_source_url": "https://[broken"},
        }]
        with patch.object(intelligence, "_fetch_project_rows", return_value=rows), \
             patch.object(intelligence, "_fetch_pipeline_runs", return_value=[]), \
             patch.object(intelligence, "_fetch_document_count", return_value=0), \
             patch("services.articles.articles_query.resolve_source_trust", return_value={}):
            for run_id in (None, "run-123"):
                with self.subTest(run_id=run_id):
                    result = get_project_intelligence(
                        {"id": 1, "hashtags": [], "keywords": []},
                        period="all",
                        run_id=run_id,
                    )
                    self.assertEqual(result["total"], 1)
                    totals = {item["platform"]: item["total"] for item in result["platforms"]}
                    self.assertEqual(totals["Web"], 1)


if __name__ == "__main__":
    unittest.main()
