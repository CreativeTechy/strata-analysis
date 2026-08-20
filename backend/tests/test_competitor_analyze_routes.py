import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi.testclient import TestClient

from services.auth import auth
from services.competitors import competitor_analysis, job_runs
import main

FAKE_USER = {"id": 1, "username": "admin", "role_id": 1, "status": "active"}


def _fake_get_current_user():
    return FAKE_USER


class AnalyzeRouteTests(unittest.TestCase):
    """POST /analyze went from a request that blocked for minutes to one that
    queues a job, so what matters is the contract the UI now depends on: the
    POST returns a run id immediately, and the status route streams progress
    until it carries the findings."""

    @classmethod
    def setUpClass(cls):
        main.app.dependency_overrides[auth.get_current_user] = _fake_get_current_user
        cls._patchers = [
            patch("services.auth.auth._enforce_csrf"),
            patch("services.auth.permissions_store.user_permission_keys",
                  return_value={"competitors.analyze", "competitors.view"}),
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

    def setUp(self):
        # Each test starts with an empty registry. Runs are process-global and
        # a queued one for this study makes the next POST attach to it instead
        # of starting another - correct behaviour (see the double-click test),
        # but it would otherwise leak between tests here.
        competitor_analysis._analysis_runs = job_runs.JobRegistry("Queued for analysis.")

    def test_post_queues_a_run_and_status_reports_progress_then_findings(self):
        findings = [{"id": 1, "headline": "Opens third roastery", "confidence": 0.8,
                     "confidence_reason": "Three independent outlets carried it."}]

        def fake_job(run_id, project_id, period_days, scrape_first, pipeline_run_id=None):
            log = competitor_analysis._analysis_runs.logger(run_id)
            log("Checking 23 article(s) from the last 30 days against each competitor...")
            log("Cafe Younes: high impact - Opens third roastery")
            competitor_analysis._analysis_runs.update(
                run_id, status="success", stage="done", generated=1,
                skipped=[], validation={"scanned": 23}, scrape_run=None,
            )

        with patch.object(competitor_analysis, "run_analysis_job", side_effect=fake_job), \
             patch("services.competitors.competitor_api.project_has_articles", return_value=True), \
             patch.object(competitor_analysis, "list_findings", return_value=findings):
            queued = self.client.post("/api/competitor/studies/5/analyze", json={"period_days": 30})
            self.assertEqual(queued.status_code, 200)
            run_id = queued.json()["run_id"]
            # The POST itself never carries results - that is the whole point.
            self.assertEqual(queued.json()["status"], "queued")
            self.assertNotIn("findings", queued.json())

            status = self.client.get(f"/api/competitor/studies/5/analyze/{run_id}")

        run = status.json()["run"]
        self.assertEqual(run["status"], "success")
        self.assertEqual(run["generated"], 1)
        self.assertIn("Opens third roastery", " ".join(e["message"] for e in run["logs"]))
        # Findings ride along on the terminal poll so the workspace renders the
        # new cards without a second round trip.
        self.assertEqual(run["findings"], findings)
        self.assertEqual(run["findings"][0]["confidence_reason"],
                         "Three independent outlets carried it.")

    def test_second_click_attaches_to_the_run_already_in_flight(self):
        """Double-clicking "Run analysis" must not start a second scrape and a
        second round of LLM calls against the same competitors."""
        with patch.object(competitor_analysis, "run_analysis_job", side_effect=lambda *a: None), \
             patch("services.competitors.competitor_api.project_has_articles", return_value=True):
            first = self.client.post("/api/competitor/studies/5/analyze", json={})
            competitor_analysis._analysis_runs.update(first.json()["run_id"], status="running")
            second = self.client.post("/api/competitor/studies/5/analyze", json={})

        self.assertEqual(second.json()["run_id"], first.json()["run_id"])

    def _queued_period(self, payload):
        """The period the job actually receives for a given request body.

        Clears the registry first: the mocked job never reaches a terminal
        status, so the run left behind by the previous call would still be
        active and this POST would attach to it instead of queuing.
        """
        competitor_analysis._analysis_runs = job_runs.JobRegistry("Queued for analysis.")
        with patch.object(competitor_analysis, "run_analysis_job") as job, \
             patch("services.competitors.competitor_api.project_has_articles", return_value=True):
            self.client.post("/api/competitor/studies/5/analyze", json=payload)
        return job.call_args[0][2]

    def test_period_selector_reaches_the_job(self):
        """The dialog's window picker is only meaningful if the value survives
        the round trip - it used to be hardcoded to 30 in the dashboard."""
        self.assertEqual(self._queued_period({"period_days": 365}), 365)
        self.assertEqual(self._queued_period({"period_days": 90}), 90)

    def test_period_is_clamped_to_a_sane_range(self):
        self.assertEqual(self._queued_period({"period_days": 99999}), 365)
        self.assertEqual(self._queued_period({"period_days": -5}), 1)
        # Absent or zero falls back to the default rather than meaning "no window".
        self.assertEqual(self._queued_period({}), competitor_analysis.DEFAULT_PERIOD_DAYS)
        self.assertEqual(self._queued_period({"period_days": 0}), competitor_analysis.DEFAULT_PERIOD_DAYS)

    def test_status_404s_for_a_run_belonging_to_another_study(self):
        run_id = competitor_analysis.create_analysis_run(999)
        response = self.client.get(f"/api/competitor/studies/5/analyze/{run_id}")
        self.assertEqual(response.status_code, 404)

    def test_scraping_without_sources_still_fails_fast_with_a_real_status(self):
        """The checks that can answer immediately stayed in the handler - moving
        them into the job would turn a 400 into a job that fails a minute later."""
        with patch("services.competitors.competitor_api.get_active_run_for_project", return_value=None), \
             patch("services.competitors.competitor_api.list_sources_for_project", return_value=[]):
            response = self.client.post("/api/competitor/studies/5/analyze", json={"scrape": True})

        self.assertEqual(response.status_code, 400)
        # main.py normalizes every HTTPException to {"error": ...}.
        self.assertIn("No sources", response.json()["error"])


class ListStudiesFindingCountTests(unittest.TestCase):
    """GET /studies' finding_count must count the same thing the study's own
    findings grid shows - one card per competitor, the newest, excluding
    rejected ones - not every row competitor_findings has ever accumulated.

    generate_finding() always INSERTs, never UPDATEs, so re-running analysis
    on an unchanged competitor set used to grow this number forever."""

    @classmethod
    def setUpClass(cls):
        main.app.dependency_overrides[auth.get_current_user] = _fake_get_current_user
        cls._patchers = [
            patch("services.auth.auth._enforce_csrf"),
            patch("services.auth.permissions_store.user_permission_keys",
                  return_value={"competitors.view"}),
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

    def test_counts_distinct_competitors_not_total_generation_events(self):
        """3 competitors, one re-analyzed twice more: 5 rows in the table, but
        the study only ever shows 3 cards."""
        from services.competitors import competitor_api

        rows = [
            {"id": 3, "name": "Study"},
        ]
        with patch("services.competitors.competitor_api.db.fetch_all", return_value=rows) as fetch_all:
            self.client.get("/api/competitor/studies")

        sql = fetch_all.call_args[0][0]
        # The rewritten query must dedupe per competitor and drop rejected
        # cards before counting - both are what made "3" the right number.
        self.assertIn("distinct on (competitor_id)", sql)
        self.assertIn("validation_status != 'rejected'", sql)
        self.assertNotIn("from competitor_findings group by project_id", sql)


if __name__ == "__main__":
    unittest.main()
