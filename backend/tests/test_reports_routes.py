"""POST /api/projects/{project_id}/reports/summary.pdf - route wiring, auth,
and cross-project run rejection. report_data.py/yesterday_comparison.py/
pdf_renderer.py's own logic is covered by their dedicated test modules; this
only asserts the endpoint composes them correctly and enforces access."""

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


class ReportsRoutesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.app.dependency_overrides[auth.get_current_user] = _fake_get_current_user
        cls._csrf_patcher = patch("services.auth.auth._enforce_csrf")
        cls._csrf_patcher.start()
        cls._perm_patcher = patch(
            "services.auth.permissions_store.user_permission_keys",
            return_value={"articles.view"},
        )
        cls._perm_patcher.start()
        cls._full_access_patcher = patch("services.auth.permissions_store.user_is_full_access", return_value=True)
        cls._full_access_patcher.start()
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        main.app.dependency_overrides.clear()
        cls._csrf_patcher.stop()
        cls._perm_patcher.stop()
        cls._full_access_patcher.stop()


class ExportSummaryPdfTests(ReportsRoutesTestCase):
    PROJECT = {"id": 1, "name": "Acme"}

    def test_404_when_project_does_not_exist(self):
        with patch("main.get_project", return_value=None):
            resp = self.client.post("/api/projects/1/reports/summary.pdf")
        self.assertEqual(resp.status_code, 404)

    def test_400_when_the_selected_run_belongs_to_a_different_project(self):
        with patch("main.get_project", return_value=self.PROJECT), \
             patch("main.get_pipeline_run", return_value={"id": "run-1", "project_id": 2}):
            resp = self.client.post("/api/projects/1/reports/summary.pdf?run_id=run-1")
        self.assertEqual(resp.status_code, 400)
        # main.py's global HTTPException handler reshapes every raised
        # HTTPException to {"error": ...} (see _http_exception_handler), not
        # FastAPI's default {"detail": ...} - matches every other route here.
        self.assertIn("does not belong to this project", resp.json()["error"])

    def test_400_when_the_selected_run_does_not_exist(self):
        with patch("main.get_project", return_value=self.PROJECT), \
             patch("main.get_pipeline_run", return_value=None):
            resp = self.client.post("/api/projects/1/reports/summary.pdf?run_id=missing")
        self.assertEqual(resp.status_code, 400)

    def test_successful_export_returns_a_pdf_with_a_meaningful_filename(self):
        with patch("main.get_project", return_value=self.PROJECT), \
             patch("main.build_report_data", return_value={"project": {"id": 1, "name": "Acme"}}) as build_data, \
             patch("main.build_variation_from_last_run", return_value={"status": "unavailable"}) as build_cmp, \
             patch("services.reports.pdf_renderer.render_summary_pdf", return_value=b"%PDF-1.7 fake") as render:
            resp = self.client.post("/api/projects/1/reports/summary.pdf?period=7d")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "application/pdf")
        self.assertIn("acme", resp.headers["content-disposition"].lower())
        self.assertIn("summary", resp.headers["content-disposition"].lower())
        self.assertEqual(resp.content, b"%PDF-1.7 fake")
        build_data.assert_called_once()
        build_cmp.assert_called_once()
        render.assert_called_once()

    def test_run_scoped_export_validates_ownership_then_builds_with_that_run(self):
        run = {"id": "run-1", "project_id": 1, "sequence_number": 2}
        with patch("main.get_project", return_value=self.PROJECT), \
             patch("main.get_pipeline_run", return_value=run), \
             patch("main.build_report_data", return_value={"project": {"id": 1, "name": "Acme"}}) as build_data, \
             patch("main.build_variation_from_last_run", return_value={"status": "unavailable"}), \
             patch("services.reports.pdf_renderer.render_summary_pdf", return_value=b"%PDF-1.7 fake"):
            resp = self.client.post("/api/projects/1/reports/summary.pdf?run_id=run-1")

        self.assertEqual(resp.status_code, 200)
        _, kwargs = build_data.call_args
        self.assertEqual(kwargs.get("run"), run)

    def test_an_llm_failure_in_the_comparison_still_exports_the_rest_of_the_report(self):
        """build_variation_from_last_run never raises - it degrades to
        status=llm_failed - so a provider outage must not turn the whole
        export into a 500."""
        with patch("main.get_project", return_value=self.PROJECT), \
             patch("main.build_report_data", return_value={"project": {"id": 1, "name": "Acme"}}), \
             patch("main.build_variation_from_last_run", return_value={"status": "llm_failed", "reason": "boom"}), \
             patch("services.reports.pdf_renderer.render_summary_pdf", return_value=b"%PDF-1.7 fake") as render:
            resp = self.client.post("/api/projects/1/reports/summary.pdf")
        self.assertEqual(resp.status_code, 200)
        render.assert_called_once()
        comparison_arg = render.call_args[0][1]
        self.assertEqual(comparison_arg["status"], "llm_failed")

    def test_rendering_failure_is_a_500_not_a_partial_pdf(self):
        with patch("main.get_project", return_value=self.PROJECT), \
             patch("main.build_report_data", return_value={"project": {"id": 1, "name": "Acme"}}), \
             patch("main.build_variation_from_last_run", return_value={"status": "unavailable"}), \
             patch("services.reports.pdf_renderer.render_summary_pdf", side_effect=RuntimeError("boom")):
            resp = self.client.post("/api/projects/1/reports/summary.pdf")
        self.assertEqual(resp.status_code, 500)

    def test_requires_articles_view_permission(self):
        with patch("services.auth.permissions_store.user_permission_keys", return_value=set()), \
             patch("services.auth.permissions_store.user_is_full_access", return_value=False):
            resp = self.client.post("/api/projects/1/reports/summary.pdf")
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
