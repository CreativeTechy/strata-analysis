"""POST /api/competitor/findings/{finding_id}/report.pdf - route wiring, auth,
and cross-project visibility. pdf_renderer.py's own rendering logic is covered
by test_pdf_renderer.py; this only asserts the endpoint composes it correctly
and enforces access, mirroring test_reports_routes.py's ExportSummaryPdfTests
for the Reports page's own summary.pdf endpoint."""

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


class CompetitorReportPdfRoutesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.app.dependency_overrides[auth.get_current_user] = _fake_get_current_user
        cls._csrf_patcher = patch("services.auth.auth._enforce_csrf")
        cls._csrf_patcher.start()
        cls._perm_patcher = patch(
            "services.auth.permissions_store.user_permission_keys",
            return_value={"competitors.view"},
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


class ExportFindingReportPdfTests(CompetitorReportPdfRoutesTestCase):
    FINDING = {"id": 7, "project_id": 1, "competitor_id": 3, "competitor_name": "Acme Foods"}

    def test_404_when_finding_does_not_exist(self):
        with patch("services.competitors.competitor_analysis.get_finding", return_value=None):
            resp = self.client.post("/api/competitor/findings/7/report.pdf")
        self.assertEqual(resp.status_code, 404)

    def test_successful_export_returns_a_pdf_with_a_meaningful_filename(self):
        with patch("services.competitors.competitor_analysis.get_finding", return_value=self.FINDING), \
             patch("services.competitors.competitor_analysis.rejected_evidence", return_value=[]) as rejected, \
             patch("services.reports.pdf_renderer.render_competitor_report_pdf", return_value=b"%PDF-1.7 fake") as render:
            resp = self.client.post("/api/competitor/findings/7/report.pdf")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "application/pdf")
        self.assertIn("acme-foods", resp.headers["content-disposition"].lower())
        self.assertEqual(resp.content, b"%PDF-1.7 fake")
        rejected.assert_called_once_with(3)
        render.assert_called_once_with(self.FINDING, [])

    def test_rendering_failure_is_a_500_not_a_partial_pdf(self):
        with patch("services.competitors.competitor_analysis.get_finding", return_value=self.FINDING), \
             patch("services.competitors.competitor_analysis.rejected_evidence", return_value=[]), \
             patch("services.reports.pdf_renderer.render_competitor_report_pdf", side_effect=RuntimeError("boom")):
            resp = self.client.post("/api/competitor/findings/7/report.pdf")
        self.assertEqual(resp.status_code, 500)

    def test_requires_competitors_view_permission(self):
        with patch("services.auth.permissions_store.user_permission_keys", return_value=set()), \
             patch("services.auth.permissions_store.user_is_full_access", return_value=False):
            resp = self.client.post("/api/competitor/findings/7/report.pdf")
        self.assertEqual(resp.status_code, 403)

    def test_404_for_a_finding_outside_the_users_visible_projects(self):
        with patch("services.competitors.competitor_analysis.get_finding", return_value=self.FINDING), \
             patch("services.auth.permissions_store.user_is_full_access", return_value=False), \
             patch("services.auth.authz.list_project_ids_for_user", return_value=[9]):
            resp = self.client.post("/api/competitor/findings/7/report.pdf")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
