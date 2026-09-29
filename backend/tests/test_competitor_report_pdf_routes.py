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


class ExportAnalysisRunReportPdfTests(CompetitorReportPdfRoutesTestCase):
    """POST /api/competitor/studies/{project_id}/analysis-runs/{run_id}/report.pdf
    - the consolidated, per-run PDF export. Mirrors ExportFindingReportPdfTests
    above for the same route-wiring/auth/visibility concerns, plus the extra
    run-vs-project scoping this route does that the single-finding one doesn't."""

    RUN = {"id": 11, "project_id": 5, "sequence_number": 2}
    FINDINGS = [
        {"id": 7, "project_id": 5, "competitor_id": 3, "competitor_name": "Acme Foods"},
        {"id": 8, "project_id": 5, "competitor_id": 4, "competitor_name": "Beta Bites"},
    ]

    def setUp(self):
        self._project_patcher = patch(
            "services.competitors.competitor_api._project_or_404",
            return_value={"id": 5, "name": "Study", "mode": "competitor"},
        )
        self._project_patcher.start()

    def tearDown(self):
        self._project_patcher.stop()

    def test_404_when_run_does_not_exist(self):
        with patch("services.competitors.analysis_runs_store.get_run", return_value=None):
            resp = self.client.post("/api/competitor/studies/5/analysis-runs/11/report.pdf")
        self.assertEqual(resp.status_code, 404)

    def test_404_when_run_belongs_to_a_different_project(self):
        other_project_run = {**self.RUN, "project_id": 999}
        with patch("services.competitors.analysis_runs_store.get_run", return_value=other_project_run):
            resp = self.client.post("/api/competitor/studies/5/analysis-runs/11/report.pdf")
        self.assertEqual(resp.status_code, 404)

    def test_400_when_the_run_has_no_findings(self):
        with patch("services.competitors.analysis_runs_store.get_run", return_value=self.RUN), \
             patch("services.competitors.competitor_analysis.list_findings", return_value=[]):
            resp = self.client.post("/api/competitor/studies/5/analysis-runs/11/report.pdf")
        self.assertEqual(resp.status_code, 400)

    def test_successful_export_returns_a_pdf_with_a_meaningful_filename(self):
        with patch("services.competitors.analysis_runs_store.get_run", return_value=self.RUN), \
             patch("services.competitors.competitor_analysis.list_findings", return_value=self.FINDINGS) as list_findings, \
             patch("services.competitors.competitor_analysis.rejected_evidence", return_value=[]) as rejected, \
             patch("services.reports.pdf_renderer.render_consolidated_competitor_report_pdf",
                   return_value=b"%PDF-1.7 fake") as render:
            resp = self.client.post("/api/competitor/studies/5/analysis-runs/11/report.pdf")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "application/pdf")
        self.assertIn("competitor-analysis-2-consolidated.pdf", resp.headers["content-disposition"])
        self.assertEqual(resp.content, b"%PDF-1.7 fake")
        list_findings.assert_called_once_with(5, analysis_run_id=11)
        self.assertEqual(rejected.call_count, 2)
        rejected.assert_any_call(3)
        rejected.assert_any_call(4)
        render.assert_called_once()
        called_run, called_findings, called_rejected = render.call_args.args
        self.assertEqual(called_run, self.RUN)
        self.assertEqual(called_findings, self.FINDINGS)
        self.assertEqual(called_rejected, {3: [], 4: []})

    def test_filename_falls_back_to_run_id_without_a_sequence_number(self):
        run_without_sequence = {"id": 11, "project_id": 5, "sequence_number": None}
        with patch("services.competitors.analysis_runs_store.get_run", return_value=run_without_sequence), \
             patch("services.competitors.competitor_analysis.list_findings", return_value=self.FINDINGS), \
             patch("services.competitors.competitor_analysis.rejected_evidence", return_value=[]), \
             patch("services.reports.pdf_renderer.render_consolidated_competitor_report_pdf",
                   return_value=b"%PDF-1.7 fake"):
            resp = self.client.post("/api/competitor/studies/5/analysis-runs/11/report.pdf")
        self.assertIn("competitor-analysis-11-consolidated.pdf", resp.headers["content-disposition"])

    def test_rendering_failure_is_a_500_not_a_partial_pdf(self):
        with patch("services.competitors.analysis_runs_store.get_run", return_value=self.RUN), \
             patch("services.competitors.competitor_analysis.list_findings", return_value=self.FINDINGS), \
             patch("services.competitors.competitor_analysis.rejected_evidence", return_value=[]), \
             patch("services.reports.pdf_renderer.render_consolidated_competitor_report_pdf",
                   side_effect=RuntimeError("boom")):
            resp = self.client.post("/api/competitor/studies/5/analysis-runs/11/report.pdf")
        self.assertEqual(resp.status_code, 500)

    def test_requires_competitors_view_permission(self):
        with patch("services.auth.permissions_store.user_permission_keys", return_value=set()), \
             patch("services.auth.permissions_store.user_is_full_access", return_value=False):
            resp = self.client.post("/api/competitor/studies/5/analysis-runs/11/report.pdf")
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
