import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.articles import articles_search


class BulkScanPagingTests(unittest.TestCase):
    """SEARCH_SCAN_LIMIT is a hard ceiling on how much of the corpus one
    search ever ranks in memory - _fetch_all_articles is this module's own
    bounded reader, distinct from articles_query.MAX_LIMIT which caps a single
    *API* page. A 900-article project exported 100 articles once because a
    bulk reader silently treated a short page as "no more rows" at the wrong
    cap; these pin the paging contract that regression came from."""

    def _fake_db(self, total, columns=("id", "url", "title")):
        rows_all = [{column: f"{column}-{i}" for column in columns} for i in range(total)]

        def fetch_all(sql, params=()):
            limit, offset = params[-2], params[-1]
            return rows_all[offset:offset + limit]

        return fetch_all

    def _run(self, total, call):
        patchers = [
            patch("services.articles.articles_query.config.DATABASE_URL", "postgresql://x"),
            patch("services.articles.articles_query.db.fetch_all", side_effect=self._fake_db(total)),
            patch("services.articles.articles_query.db.fetch_one", return_value={"total": total}),
        ]
        for patcher in patchers:
            patcher.start()
        try:
            return call()
        finally:
            for patcher in patchers:
                patcher.stop()

    def test_search_scan_reaches_its_own_limit_not_the_api_page_cap(self):
        rows = self._run(900, lambda: articles_search._fetch_all_articles(limit=articles_search.SEARCH_SCAN_LIMIT))
        self.assertEqual(len(rows), 900)

    def test_search_scan_still_stops_at_search_scan_limit(self):
        rows = self._run(2500, lambda: articles_search._fetch_all_articles(limit=articles_search.SEARCH_SCAN_LIMIT))
        self.assertEqual(len(rows), articles_search.SEARCH_SCAN_LIMIT)


class ScoreSearchRowTests(unittest.TestCase):
    def test_exact_phrase_hit_matches_and_scores_highest(self):
        row = {"title": "Stellantis battery recall", "summary": "", "text": ""}
        score, matched = articles_search._score_search_row(row, "Stellantis battery recall")
        self.assertTrue(matched)
        self.assertGreater(score, 0.9)

    def test_every_keyword_token_must_hit_not_just_one(self):
        """A query like "Stellantis battery" must not match every article
        merely because "Stellantis" (a project's every title) appears alone."""
        row = {"title": "Stellantis quarterly earnings", "summary": "", "text": ""}
        score, matched = articles_search._score_search_row(row, "Stellantis battery")
        self.assertFalse(matched)

    def test_no_overlap_does_not_match(self):
        row = {"title": "Unrelated headline", "summary": "", "text": ""}
        score, matched = articles_search._score_search_row(row, "Stellantis battery")
        self.assertEqual(score, 0.0)
        self.assertFalse(matched)

    def test_empty_blob_does_not_match(self):
        row = {"title": "", "summary": "", "text": ""}
        score, matched = articles_search._score_search_row(row, "Stellantis")
        self.assertEqual(score, 0.0)
        self.assertFalse(matched)


class RankSearchRowsTests(unittest.TestCase):
    def test_matched_rows_are_returned_ranked_by_score(self):
        rows = [
            {"id": 1, "title": "Stellantis quarterly earnings", "summary": "", "text": ""},
            {"id": 2, "title": "Stellantis battery recall widens", "summary": "", "text": ""},
        ]
        ranked, matched = articles_search._rank_search_rows(rows, "Stellantis battery recall")
        self.assertEqual([row["id"] for row in ranked], [2])
        self.assertEqual(matched, ranked)

    def test_no_matches_falls_back_to_top_scored_rows(self):
        rows = [{"id": 1, "title": "Unrelated headline", "summary": "", "text": ""}]
        ranked, matched = articles_search._rank_search_rows(rows, "Stellantis battery recall")
        self.assertEqual(ranked, rows)
        self.assertEqual(matched, rows)

    def test_empty_search_returns_rows_unranked(self):
        rows = [{"id": 1, "title": "Anything"}]
        ranked, matched = articles_search._rank_search_rows(rows, "")
        self.assertEqual(ranked, rows)
        self.assertEqual(matched, [])


class SearchResultsTests(unittest.TestCase):
    def test_ranks_the_bulk_scan_against_the_search_term(self):
        rows = [
            {"id": 1, "title": "Stellantis quarterly earnings", "summary": "", "text": ""},
            {"id": 2, "title": "Stellantis battery recall widens", "summary": "", "text": ""},
        ]
        with patch("services.articles.articles_search._fetch_all_articles", return_value=rows):
            ranked, total = articles_search.search_results(search="Stellantis battery recall")
        self.assertEqual([row["id"] for row in ranked], [2])
        self.assertEqual(total, 1)

    def test_no_search_term_returns_the_full_scan_unranked(self):
        rows = [{"id": 1, "title": "Anything"}]
        with patch("services.articles.articles_search._fetch_all_articles", return_value=rows):
            ranked, total = articles_search.search_results()
        self.assertEqual(ranked, rows)
        self.assertEqual(total, 1)


if __name__ == "__main__":
    unittest.main()
