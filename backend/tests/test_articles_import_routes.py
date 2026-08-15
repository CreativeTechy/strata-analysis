import io
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi.testclient import TestClient

from services.articles import articles_store
from services.auth import auth
import main

FAKE_USER = {"id": 1, "username": "admin", "role_id": 1, "status": "active"}


def _fake_get_current_user():
    return FAKE_USER


class ExportSelectTests(unittest.TestCase):
    """The export exists to be re-importable, and the upsert behind the import
    writes every mutable column from `excluded` - so any column the upsert
    writes but the export omits comes back NULL on a round trip."""

    def test_export_selects_every_column_the_upsert_writes(self):
        from services.articles.store import stored_article_fields

        articles_store._export_select.cache_clear()
        selected = articles_store._export_select().split(",")
        missing = [field for field in stored_article_fields() if field not in selected]
        self.assertEqual(missing, [])

    def test_export_still_carries_what_the_dashboard_list_shows(self):
        articles_store._export_select.cache_clear()
        selected = set(articles_store._export_select().split(","))
        dropped = [field for field in articles_store.ARTICLES_SELECT.split(",") if field not in selected]
        self.assertEqual(dropped, [])


class ImportRouteTests(unittest.TestCase):
    """POST /api/articles/import restores an export through the same
    save_articles() the pipeline's saver uses. What matters here is what
    reaches that call: only writable columns, batched, with unusable lines
    reported rather than aborting the whole file."""

    @classmethod
    def setUpClass(cls):
        main.app.dependency_overrides[auth.get_current_user] = _fake_get_current_user
        cls._patchers = [
            patch("services.auth.auth._enforce_csrf"),
            patch("services.auth.permissions_store.user_permission_keys",
                  return_value={"articles.view", "articles.import"}),
            patch("services.auth.permissions_store.user_is_full_access", return_value=True),
        ]
        for patcher in cls._patchers:
            patcher.start()
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        main.app.dependency_overrides.clear()
        for patcher in cls._patchers:
            patcher.stop()

    def setUp(self):
        self.saved_batches = []

        def fake_save_articles(articles, batch_size=50, project_id=None):
            self.saved_batches.append(list(articles))
            return len(articles), {"Fake Source": len(articles)}

        patcher = patch("services.articles.store.save_articles", side_effect=fake_save_articles)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, lines, data=None):
        payload = "\n".join(lines).encode("utf-8")
        return self.client.post(
            "/api/articles/import",
            files={"file": ("articles.jsonl", io.BytesIO(payload), "application/x-ndjson")},
            data=data or {},
        )

    def test_imports_rows_and_drops_keys_the_upsert_cannot_write(self):
        row = {
            "id": 4242,                      # this database's key, not the target's
            "created_at": "2026-01-01T00:00:00Z",
            "project_similarity_score": 0.4,  # computed by the export, not a column
            "url": "https://example.com/a",
            "title": "A",
            "text": "body",
            "sentiment_score": 0.91,          # only exportable since the select widened
            "analysis_status": "success",
        }
        res = self._post([json.dumps(row), "", json.dumps({**row, "url": "https://example.com/b"})])

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual((body["received"], body["saved"], body["skipped"]), (2, 2, 0))
        sent = self.saved_batches[0][0]
        self.assertNotIn("id", sent)
        self.assertNotIn("created_at", sent)
        self.assertNotIn("project_similarity_score", sent)
        self.assertEqual(sent["sentiment_score"], 0.91)
        self.assertEqual(sent["analysis_status"], "success")

    def test_unusable_lines_are_reported_and_the_rest_still_import(self):
        good = json.dumps({"url": "https://example.com/a", "title": "A"})
        res = self._post(["{not json", json.dumps({"title": "no url"}), "[1,2]", good])

        body = res.json()
        self.assertEqual((body["received"], body["saved"], body["skipped"]), (1, 1, 3))
        self.assertEqual([item["line"] for item in body["errors"]], [1, 2, 3])

    def test_a_json_array_file_is_rejected_with_a_usable_message(self):
        res = self._post(["[", json.dumps({"url": "https://example.com/a"}), "]"])
        self.assertEqual(res.status_code, 400)
        # main.py reshapes every HTTPException into {"error": detail}.
        self.assertIn("JSON Lines", res.json()["error"])
        self.assertEqual(self.saved_batches, [])

    def test_a_file_with_nothing_importable_is_a_400_not_an_empty_success(self):
        res = self._post(["", "   "])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.saved_batches, [])

    def test_large_files_are_saved_in_batches_rather_than_one_call(self):
        lines = [
            json.dumps({"url": f"https://example.com/{i}", "title": str(i)})
            for i in range(main.IMPORT_BATCH_SIZE + 5)
        ]
        res = self._post(lines)

        body = res.json()
        self.assertEqual([len(batch) for batch in self.saved_batches], [main.IMPORT_BATCH_SIZE, 5])
        self.assertEqual(body["saved"], main.IMPORT_BATCH_SIZE + 5)
        self.assertEqual(body["by_source"], {"Fake Source": main.IMPORT_BATCH_SIZE + 5})

    def test_project_scope_is_passed_through_to_the_saver(self):
        with patch("main._ensure_project_visible") as ensure_visible:
            res = self._post([json.dumps({"url": "https://example.com/a"})], data={"project_id": "7"})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["project_id"], 7)
        ensure_visible.assert_called_once()
        self.assertEqual(ensure_visible.call_args.args[0], 7)


if __name__ == "__main__":
    unittest.main()
