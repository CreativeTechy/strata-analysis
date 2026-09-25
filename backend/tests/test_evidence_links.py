import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi.testclient import TestClient

from services.auth import auth
from services.intelligence import evidence_links, intelligence
from services.intelligence.intelligence import get_project_intelligence
import main

FAKE_USER = {"id": 1, "username": "admin", "role_id": 1, "status": "active"}
NOW = datetime.now(timezone.utc)


def _days_ago(days):
    return (NOW - timedelta(days=days)).isoformat()


# A deliberately mixed project: every dashboard dimension has more than one
# bucket, including the "unknown"/missing ones the aggregation invents.
ROWS = [
    {"id": 1, "url": "document://project-document/1#a", "source": "report.pdf", "source_url": "document://project-document/1",
     "sentiment": "negative", "source_language": "en", "region": "Gulf", "gender": "female", "age_range": "25-34", "segment": "Retail",
     "article_tone": "angry", "writer_tone": "angry", "published": _days_ago(2)},
    {"id": 2, "url": "https://x.com/a/status/1", "source": "x.com", "source_url": "document://project-document/2",
     "sentiment": "Negative", "source_language": "AR", "region": "Levant", "gender": None, "age_range": "", "segment": None,
     "article_tone": "critical", "writer_tone": "neutral", "published": _days_ago(3)},
    {"id": 3, "url": "https://news.example.com/b", "source": "news", "source_url": "document://project-document/2",
     "sentiment": "positive", "source_language": None, "region": "Gulf", "gender": "male", "age_range": "25-34", "segment": "Retail",
     "article_tone": "optimistic", "writer_tone": "neutral", "published": _days_ago(3)},
    {"id": 4, "url": "https://reddit.com/r/a/comments/1", "source": "reddit", "source_url": "document://project-document/3",
     "sentiment": "neutral", "source_language": "en", "region": None, "gender": "female", "age_range": "45-54", "segment": "Fleet",
     "article_tone": "neutral", "writer_tone": "neutral", "published": _days_ago(10)},
    {"id": 5, "url": "document://project-document/3#b", "source": "memo.docx", "source_url": "document://project-document/3",
     "sentiment": "mixed", "source_language": "en", "region": "Gulf", "gender": "female", "age_range": "25-34", "segment": "Retail",
     "article_tone": "concerned", "writer_tone": "concerned", "published": _days_ago(60)},
]

TRUST = {"real:x.com": {"tier": "untrusted"}, "real:news.example.com": {"tier": "trusted"}}


def _trust_for(groups, project_id=None):
    return {group["key"]: TRUST[group["key"]] for group in groups if group["key"] in TRUST}


class ResolveEvidenceTests(unittest.TestCase):
    def _resolve(self, period="all", run_id=None, **filters):
        with patch.object(intelligence, "_fetch_project_rows", return_value=[dict(row) for row in ROWS]), \
             patch("services.articles.articles_query.resolve_source_trust", side_effect=_trust_for), \
             patch("services.articles.articles_query.config.DATABASE_URL", "postgres://test"):
            return evidence_links.resolve_evidence(7, period=period, run_id=run_id, filters=filters)

    def _intelligence(self, period="all"):
        with patch.object(intelligence, "_fetch_project_rows", return_value=[dict(row) for row in ROWS]), \
             patch.object(intelligence, "_fetch_pipeline_runs", return_value=[]), \
             patch.object(intelligence, "_fetch_document_count", return_value=0), \
             patch("services.articles.articles_query.resolve_source_trust", side_effect=_trust_for), \
             patch("services.articles.articles_query.config.DATABASE_URL", "postgres://test"):
            return get_project_intelligence({"id": 7, "hashtags": [], "keywords": []}, period=period)

    def test_every_dashboard_bucket_opens_exactly_as_many_articles_as_it_counted(self):
        """The point of an evidence link: the number on the chart and the
        number of articles it opens can't disagree."""
        for period in ("7d", "30d", "all"):
            data = self._intelligence(period)
            insights = data["insights"]
            buckets = [("sentiment", key, data[key]) for key in ("positive", "negative", "neutral", "mixed")]
            buckets += [("platform", item["platform"], item["total"]) for item in data["platforms"]]
            buckets += [("language", item["language"], item["count"]) for item in insights["language_breakdown"]]
            for dimension in ("region", "gender", "age_range", "segment"):
                buckets += [(dimension, item["value"], item["total"]) for item in insights[f"{dimension}_breakdown"]]
            buckets += [("trust", tier, values["articles"]) for tier, values in data["source_trust"]["tiers"].items()]
            buckets += [("emotion", item["axis"], item["count"]) for item in data["emotional_signature"]]
            buckets += [("date", item["date"], item["total"]) for item in data["sentiment_over_time"]]
            self.assertGreater(len(buckets), 20)
            for dimension, value, count in buckets:
                with self.subTest(period=period, dimension=dimension, value=value):
                    self.assertEqual(len(self._resolve(period=period, **{dimension: value}).article_ids), count)
            with self.subTest(period=period, dimension="scope"):
                self.assertEqual(len(self._resolve(period=period).article_ids), data["total"])

    def test_sentiment_by_platform_cells_combine_both_filters(self):
        data = self._intelligence("all")
        for item in data["platforms"]:
            for sentiment in ("positive", "negative", "neutral", "mixed"):
                with self.subTest(platform=item["platform"], sentiment=sentiment):
                    match = self._resolve(platform=item["platform"], sentiment=sentiment)
                    self.assertEqual(len(match.article_ids), item[sentiment])

    def test_period_scope_drops_articles_outside_the_window(self):
        self.assertEqual(sorted(self._resolve(period="7d").article_ids), [1, 2, 3])
        self.assertEqual(sorted(self._resolve(period="30d").article_ids), [1, 2, 3, 4])
        self.assertEqual(sorted(self._resolve(period="7d", sentiment="negative").article_ids), [1, 2])

    def test_no_period_means_no_date_window(self):
        self.assertEqual(sorted(self._resolve(period=None).article_ids), [1, 2, 3, 4, 5])

    def test_unknown_buckets_match_missing_values(self):
        self.assertEqual(self._resolve(gender="unknown").article_ids, [2])
        self.assertEqual(self._resolve(language="unknown").article_ids, [3])
        self.assertEqual(sorted(self._resolve(trust="unknown").article_ids), [1, 4, 5])

    def test_run_scope_reads_the_runs_snapshot_rows_and_keeps_them_for_the_overlay(self):
        snapshot_rows = [dict(ROWS[0], sentiment="positive", summary="as run 3 saw it")]
        with patch.object(intelligence, "_fetch_project_rows", return_value=snapshot_rows) as fetch:
            match = evidence_links.resolve_evidence(7, period="7d", run_id="run-3", filters={"sentiment": "positive"})
        fetch.assert_called_once_with(7, run_id="run-3")
        self.assertEqual(match.article_ids, [1])

        listed = [{"id": 1, "sentiment": "negative", "summary": "latest", "title": "Live title"}]
        evidence_links.overlay_snapshots(listed, match, "run-3")
        self.assertEqual(listed[0]["sentiment"], "positive")
        self.assertEqual(listed[0]["summary"], "as run 3 saw it")
        self.assertEqual(listed[0]["title"], "Live title")
        self.assertEqual(listed[0]["analysis_run_id"], "run-3")

    def test_no_overlay_outside_run_scope(self):
        match = self._resolve(sentiment="negative")
        listed = [{"id": 1, "sentiment": "negative"}]
        evidence_links.overlay_snapshots(listed, match, None)
        self.assertNotIn("analysis_run_id", listed[0])


class ArticleIdRestrictionTests(unittest.TestCase):
    def test_an_empty_id_set_matches_nothing_rather_than_everything(self):
        from services.articles.articles_query import _where_parts

        where_sql, params = _where_parts(article_ids=[])
        self.assertIn("id = -1", where_sql)
        where_sql, params = _where_parts(article_ids=[3, 5], sentiment="negative")
        self.assertIn("id = any(%s)", where_sql)
        self.assertEqual(params[0], [3, 5])
        self.assertIsNone(_where_parts()[0] or None)


class ArticlesEvidenceRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.app.dependency_overrides[auth.get_current_user] = lambda: FAKE_USER
        cls._patchers = [
            patch("services.auth.auth._enforce_csrf"),
            patch("services.auth.permissions_store.user_permission_keys", return_value={"articles.view"}),
            patch("services.auth.permissions_store.user_is_full_access", return_value=True),
            patch("main._ensure_project_visible"),
        ]
        for patcher in cls._patchers:
            patcher.start()
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        main.app.dependency_overrides.clear()
        for patcher in cls._patchers:
            patcher.stop()

    def _list_result(self, rows=None):
        return {"articles": rows or [], "total": len(rows or []), "limit": 24, "offset": 0, "sort": "published.desc"}

    def test_a_plain_sentiment_filter_stays_a_column_filter(self):
        with patch("main.list_articles", return_value=self._list_result()) as listing, \
             patch.object(evidence_links, "resolve_evidence") as resolve:
            res = self.client.get("/api/articles", params={"sentiment": "negative"})
        self.assertEqual(res.status_code, 200)
        resolve.assert_not_called()
        self.assertEqual(listing.call_args.kwargs["sentiment"], "negative")
        self.assertIsNone(listing.call_args.kwargs["article_ids"])

    def test_a_scoped_selection_lists_the_resolved_ids(self):
        match = evidence_links.EvidenceMatch(article_ids=[4, 9])
        with patch("main.list_articles", return_value=self._list_result()) as listing, \
             patch.object(evidence_links, "resolve_evidence", return_value=match) as resolve:
            res = self.client.get("/api/articles", params={"project_id": 7, "period": "7d", "sentiment": "negative", "region": "Gulf"})
        self.assertEqual(res.status_code, 200)
        resolve.assert_called_once_with(7, period="7d", run_id=None, filters={"sentiment": "negative", "region": "Gulf"})
        self.assertIsNone(listing.call_args.kwargs["sentiment"])
        self.assertEqual(listing.call_args.kwargs["article_ids"], [4, 9])
        self.assertEqual(listing.call_args.kwargs["project_id"], 7)

    def test_run_scope_overlays_the_snapshot_onto_listed_rows(self):
        match = evidence_links.EvidenceMatch(article_ids=[4], snapshots={4: {"sentiment": "negative"}})
        rows = [{"id": 4, "sentiment": "positive"}]
        with patch("main.get_pipeline_run", return_value={"id": "run-3", "project_id": 7}), \
             patch("main.list_articles", return_value=self._list_result(rows)), \
             patch.object(evidence_links, "resolve_evidence", return_value=match):
            res = self.client.get("/api/articles", params={"project_id": 7, "run_id": "run-3", "sentiment": "negative"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["articles"][0]["sentiment"], "negative")
        self.assertEqual(res.json()["articles"][0]["analysis_run_id"], "run-3")

    def test_a_run_from_another_project_is_refused(self):
        with patch("main.get_pipeline_run", return_value={"id": "run-3", "project_id": 8}):
            res = self.client.get("/api/articles", params={"project_id": 7, "run_id": "run-3"})
        self.assertEqual(res.status_code, 400)

    def test_an_unknown_run_is_not_found(self):
        with patch("main.get_pipeline_run", return_value=None):
            res = self.client.get("/api/articles", params={"project_id": 7, "run_id": "missing"})
        self.assertEqual(res.status_code, 404)

    def test_an_unknown_period_is_refused_rather_than_silently_widened(self):
        res = self.client.get("/api/articles", params={"project_id": 7, "period": "90d"})
        self.assertEqual(res.status_code, 400)

    def test_a_chart_filter_without_a_project_is_refused(self):
        res = self.client.get("/api/articles", params={"platform": "X"})
        self.assertEqual(res.status_code, 400)

    def test_the_export_applies_the_same_scope(self):
        match = evidence_links.EvidenceMatch(article_ids=[4])
        with patch("main.export_articles", return_value=iter([])) as export, \
             patch.object(evidence_links, "resolve_evidence", return_value=match):
            res = self.client.get("/api/articles/export", params={"project_id": 7, "period": "30d", "platform": "X"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(export.call_args.kwargs["article_ids"], [4])


if __name__ == "__main__":
    unittest.main()
