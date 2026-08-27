import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi.testclient import TestClient

from services.auth import auth
import main

FAKE_USER = {"id": 1, "username": "admin", "role_id": 1, "status": "active"}


def _fake_get_current_user():
    return FAKE_USER


class ImportCompetitorsRouteTests(unittest.TestCase):
    """POST /studies/{project_id}/competitors/import - the companion to the
    scraper app's GET /api/competitors/export, so a competitor list already
    confirmed there doesn't need to be re-guessed by document_analysis.py's
    LLM pass or re-typed by hand."""

    @classmethod
    def setUpClass(cls):
        main.app.dependency_overrides[auth.get_current_user] = _fake_get_current_user
        cls._patchers = [
            patch("services.auth.auth._enforce_csrf"),
            patch("services.auth.permissions_store.user_permission_keys",
                  return_value={"competitors.manage", "competitors.view"}),
            patch("services.auth.permissions_store.user_is_full_access", return_value=True),
            patch("services.competitors.competitor_api._project_or_404",
                  return_value={"id": 5, "name": "Study", "mode": "competitor"}),
        ]
        for patcher in cls._patchers:
            patcher.start()
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        main.app.dependency_overrides.clear()
        for patcher in cls._patchers:
            patcher.stop()

    def _upload(self, body: str):
        return self.client.post(
            "/api/competitor/studies/5/competitors/import",
            files={"file": ("competitors-export.jsonl", body, "application/x-ndjson")},
        )

    def test_each_line_is_upserted_and_reranked(self):
        rows = [
            {"name": "Cafe Younes", "domain": "cafeyounes.com", "status": "tracked"},
            {"name": "Deluxe Coffee"},
        ]
        body = "\n".join(json.dumps(r) for r in rows) + "\n"

        with patch("services.competitors.competitor_api.competitors_store.upsert_competitor",
                    side_effect=lambda project_id, values: {"id": 1, **values}) as upsert, \
             patch("services.competitors.competitor_api.competitors_store.rerank_competitors") as rerank:
            res = self._upload(body)

        self.assertEqual(res.status_code, 200)
        payload = res.json()
        self.assertEqual(payload["received"], 2)
        self.assertEqual(payload["saved"], 2)
        self.assertEqual(upsert.call_count, 2)
        # A row that doesn't say where it came from is attributed to the
        # scraper import, not silently defaulted to the manual/'ai' source.
        first_call_values = upsert.call_args_list[0].args[1]
        self.assertEqual(first_call_values["discovery_source"], "scraper_import")
        rerank.assert_called_once_with(5)

    def test_rows_missing_a_name_are_skipped_not_fatal(self):
        body = json.dumps({"name": "Cafe Younes"}) + "\n" + json.dumps({"domain": "no-name.com"}) + "\n"

        with patch("services.competitors.competitor_api.competitors_store.upsert_competitor",
                    return_value={"id": 1}), \
             patch("services.competitors.competitor_api.competitors_store.rerank_competitors"):
            res = self._upload(body)

        payload = res.json()
        self.assertEqual(payload["received"], 1)
        self.assertEqual(payload["saved"], 1)
        self.assertEqual(len(payload["errors"]), 1)

    def test_empty_file_is_rejected(self):
        res = self._upload("")
        self.assertEqual(res.status_code, 400)
        self.assertIn("empty", res.json()["error"])

    def test_a_json_array_is_rejected_with_a_clear_message(self):
        res = self._upload("[]")
        self.assertEqual(res.status_code, 400)
        self.assertIn("JSON Lines", res.json()["error"])

    def test_a_wholly_rejected_file_fails_loudly_rather_than_reporting_success(self):
        """upsert_competitor returning None for every row (e.g. a save
        failure) must not report success having saved nothing - the same
        guard the article import has for a wholly-rejected batch."""
        body = json.dumps({"name": "Cafe Younes"}) + "\n"
        with patch("services.competitors.competitor_api.competitors_store.upsert_competitor",
                    return_value=None):
            res = self._upload(body)

        self.assertEqual(res.status_code, 400)
        self.assertIn("rejected", res.json()["error"])


if __name__ == "__main__":
    unittest.main()
