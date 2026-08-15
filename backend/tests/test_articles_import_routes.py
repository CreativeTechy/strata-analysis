import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi.testclient import TestClient

from services.articles import articles_store, import_jobs
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


class ExportRouteTests(unittest.TestCase):
    """GET /api/articles/export writes NDJSON straight off the generator, so
    rows are pulled from the database as the response is written rather than
    collected first."""

    @classmethod
    def setUpClass(cls):
        main.app.dependency_overrides[auth.get_current_user] = _fake_get_current_user
        cls._patchers = [
            patch("services.auth.auth._enforce_csrf"),
            patch("services.auth.permissions_store.user_permission_keys", return_value={"articles.view"}),
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

    def test_the_response_is_one_json_object_per_line(self):
        rows = [{"id": i, "url": f"https://example.com/{i}", "title": f"T{i}"} for i in range(3)]
        with patch("main.export_articles", return_value=iter(rows)):
            res = self.client.get("/api/articles/export")

        self.assertEqual(res.status_code, 200)
        self.assertIn("application/x-ndjson", res.headers["content-type"])
        self.assertIn("attachment", res.headers["content-disposition"])
        lines = [json.loads(line) for line in res.text.splitlines() if line.strip()]
        self.assertEqual(lines, rows)

    def test_rows_are_pulled_lazily_as_the_response_is_written(self):
        pulled = []

        def lazy_rows():
            for i in range(3):
                pulled.append(i)
                yield {"id": i, "url": f"https://example.com/{i}"}

        with patch("main.export_articles", return_value=lazy_rows()):
            self.assertEqual(pulled, [])  # the generator is not drained up front
            res = self.client.get("/api/articles/export")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(pulled, [0, 1, 2])


class ImportRouteTests(unittest.TestCase):
    """POST /api/articles/import spools the upload and queues a job; the work
    itself happens in import_jobs. What matters at the route is that a file it
    cannot possibly import fails fast with a real status code, and that
    anything else comes back as a pollable run id.

    TestClient runs BackgroundTasks inline once the response is produced, so a
    successful POST here also exercises the job end to end.
    """

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

        patcher = patch("services.articles.import_jobs.save_articles", side_effect=fake_save_articles)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, lines, data=None):
        payload = "\n".join(lines).encode("utf-8")
        return self.client.post(
            "/api/articles/import",
            files={"file": ("articles.jsonl", io.BytesIO(payload), "application/x-ndjson")},
            data=data or {},
        )

    def _import(self, lines, data=None):
        """POST, then read back the run the inline BackgroundTask just finished."""
        res = self._post(lines, data)
        self.assertEqual(res.status_code, 200, res.text)
        run_id = res.json()["run_id"]
        status = self.client.get(f"/api/articles/import/{run_id}")
        self.assertEqual(status.status_code, 200, status.text)
        return res.json(), status.json()["run"]

    def test_post_returns_a_run_id_immediately_with_a_line_estimate(self):
        row = json.dumps({"url": "https://example.com/a", "title": "A"})
        queued, run = self._import([row, row.replace("/a", "/b")])

        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["total_lines"], 2)
        self.assertEqual(run["status"], "success")
        self.assertEqual((run["received"], run["saved"], run["skipped"]), (2, 2, 0))

    def test_import_drops_keys_the_upsert_cannot_write(self):
        row = {
            "id": 4242,                       # this database's key, not the target's
            "created_at": "2026-01-01T00:00:00Z",
            "project_similarity_score": 0.4,  # computed by the export, not a column
            "url": "https://example.com/a",
            "title": "A",
            "sentiment_score": 0.91,          # only exportable since the select widened
            "analysis_status": "success",
        }
        self._import([json.dumps(row)])

        sent = self.saved_batches[0][0]
        self.assertNotIn("id", sent)
        self.assertNotIn("created_at", sent)
        self.assertNotIn("project_similarity_score", sent)
        self.assertEqual(sent["sentiment_score"], 0.91)
        self.assertEqual(sent["analysis_status"], "success")

    def test_unusable_lines_are_reported_and_the_rest_still_import(self):
        good = json.dumps({"url": "https://example.com/a", "title": "A"})
        _, run = self._import(["{not json", json.dumps({"title": "no url"}), "[1,2]", good])

        self.assertEqual((run["received"], run["saved"], run["skipped"]), (1, 1, 3))
        self.assertEqual([item["line"] for item in run["errors"]], [1, 2, 3])
        self.assertEqual(run["status"], "success")

    def test_a_json_array_file_is_rejected_before_anything_is_queued(self):
        res = self._post(["[", json.dumps({"url": "https://example.com/a"}), "]"])
        self.assertEqual(res.status_code, 400)
        # main.py reshapes every HTTPException into {"error": detail}.
        self.assertIn("JSON Lines", res.json()["error"])
        self.assertEqual(self.saved_batches, [])

    def test_an_empty_upload_is_rejected_before_anything_is_queued(self):
        res = self._post([])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self.saved_batches, [])

    def test_a_file_with_no_importable_rows_fails_the_run(self):
        _, run = self._import([json.dumps({"title": "no url"})])
        self.assertEqual(run["status"], "failed")
        self.assertIn("Nothing to import", run["message"])

    def test_rows_are_saved_in_batches_rather_than_one_call(self):
        lines = [
            json.dumps({"url": f"https://example.com/{i}", "title": str(i)})
            for i in range(import_jobs.BATCH_SIZE + 5)
        ]
        _, run = self._import(lines)

        self.assertEqual([len(batch) for batch in self.saved_batches], [import_jobs.BATCH_SIZE, 5])
        self.assertEqual(run["saved"], import_jobs.BATCH_SIZE + 5)
        self.assertEqual(run["by_source"], {"Fake Source": import_jobs.BATCH_SIZE + 5})

    def test_the_run_reports_throughput_and_a_final_summary(self):
        lines = [json.dumps({"url": f"https://example.com/{i}"}) for i in range(50)]
        _, run = self._import(lines)

        self.assertGreater(run["rate_per_second"], 0)
        self.assertGreaterEqual(run["elapsed_seconds"], 0)
        self.assertEqual(run["processed"], 50)
        self.assertEqual(run["total_lines"], 50)
        messages = [entry["message"] for entry in run["logs"]]
        self.assertTrue(messages[0].startswith("Importing articles.jsonl"))
        self.assertRegex(messages[-1], r"Imported 50 articles in .+ \(\d[\d,]*/s\)\.")

    def test_project_scope_is_passed_through_to_the_saver(self):
        with patch("main._ensure_project_visible") as ensure_visible:
            queued, run = self._import([json.dumps({"url": "https://example.com/a"})], data={"project_id": "7"})

        self.assertEqual(queued["project_id"], 7)
        self.assertEqual(run["project_id"], 7)
        ensure_visible.assert_called_once()
        self.assertEqual(ensure_visible.call_args.args[0], 7)

    def test_an_unknown_run_id_is_a_404(self):
        self.assertEqual(self.client.get("/api/articles/import/nope").status_code, 404)

    def test_the_spooled_upload_is_deleted_once_the_job_finishes(self):
        seen = {}
        real_run = import_jobs.run_import_job

        def capture(run_id, path, project_id=None):
            seen["path"] = path
            return real_run(run_id, path, project_id)

        with patch("main.run_import_job", side_effect=capture):
            self._import([json.dumps({"url": "https://example.com/a"})])

        self.assertFalse(os.path.exists(seen["path"]))


class ImportJobFailureTests(unittest.TestCase):
    """A job that dies partway through still has to leave the run terminal and
    clean up its spool file - the UI polls until one of those states."""

    def test_a_saver_failure_fails_the_run_and_removes_the_spool(self):
        run_id = import_jobs.create_import_run(project_id=None, filename="x.jsonl", total_lines=1)
        handle, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(handle, "w", encoding="utf-8") as spool:
            spool.write(json.dumps({"url": "https://example.com/a"}) + "\n")

        with patch("services.articles.import_jobs.save_articles", side_effect=RuntimeError("db is down")):
            import_jobs.run_import_job(run_id, path, None)

        run = import_jobs.get_import_run(run_id)
        self.assertEqual(run["status"], "failed")
        self.assertIn("db is down", run["error"])
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
