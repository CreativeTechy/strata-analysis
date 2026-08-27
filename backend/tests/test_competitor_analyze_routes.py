import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi.testclient import TestClient

from services.auth import auth
from services.competitors import analysis_runs_store, competitor_analysis
import main

FAKE_USER = {"id": 1, "username": "admin", "role_id": 1, "status": "active"}


def _fake_get_current_user():
    return FAKE_USER


class _FakeAnalysisRuns:
    """A minimal in-memory stand-in for analysis_runs_store's Postgres-backed
    functions, so route tests can exercise the queue/attach/poll contract
    without a real database - the same role job_runs.JobRegistry played
    before analysis runs were persisted."""

    def __init__(self):
        self._runs: dict[int, dict] = {}
        self._next_id = 1
        self._sequence: dict[int, int] = {}

    def create_run(self, project_id, scope):
        run_id = self._next_id
        self._next_id += 1
        self._sequence[project_id] = self._sequence.get(project_id, 0) + 1
        run = {
            "id": run_id, "project_id": project_id, "sequence_number": self._sequence[project_id],
            "status": "queued", "scope": scope, "generated": 0, "skipped": [],
            "validation": None, "error": None, "logs": [],
            "started_at": None, "finished_at": None,
        }
        self._runs[run_id] = run
        return dict(run)

    def get_run(self, run_id):
        run = self._runs.get(run_id)
        return dict(run) if run else None

    def get_active_run(self, project_id):
        for run in self._runs.values():
            if run["project_id"] == project_id and run["status"] in ("queued", "running"):
                return dict(run)
        return None

    def append_log(self, run_id, message):
        self._runs[run_id]["logs"].append({"ts": "now", "message": message})

    def logger(self, run_id):
        return lambda message: self.append_log(run_id, message)

    def mark_success(self, run_id, generated, skipped=None, validation=None):
        self._runs[run_id].update(
            status="success", generated=generated, skipped=skipped or [], validation=validation,
        )
        return dict(self._runs[run_id])


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
        # Each test starts with an empty, fresh fake registry - it would
        # otherwise leak an active run between tests (see the double-click
        # test).
        self.fake = _FakeAnalysisRuns()
        self._run_patchers = [
            patch.object(analysis_runs_store, "create_run", side_effect=self.fake.create_run),
            patch.object(analysis_runs_store, "get_run", side_effect=self.fake.get_run),
            patch.object(analysis_runs_store, "get_active_run", side_effect=self.fake.get_active_run),
        ]
        for patcher in self._run_patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_post_queues_a_run_and_status_reports_progress_then_findings(self):
        findings = [{"id": 1, "headline": "Opens third roastery", "confidence": 0.8,
                     "confidence_reason": "Three independent outlets carried it."}]

        def fake_job(run_id, project_id, scope, document_ids=None):
            log = self.fake.logger(run_id)
            log("Checking 23 article(s) from the selected documents against each competitor...")
            log("Cafe Younes: high impact - Opens third roastery")
            self.fake.mark_success(run_id, 1, [], {"scanned": 23})

        with patch.object(competitor_analysis, "run_analysis_job", side_effect=fake_job), \
             patch("services.competitors.competitor_api.project_has_articles", return_value=True), \
             patch.object(competitor_analysis, "list_findings", return_value=findings):
            queued = self.client.post("/api/competitor/studies/5/analyze", json={"scope": "all"})
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
        """Double-clicking "Run analysis" must not start a second round of LLM
        calls against the same competitors."""
        with patch.object(competitor_analysis, "run_analysis_job", side_effect=lambda *a: None), \
             patch("services.competitors.competitor_api.project_has_articles", return_value=True):
            first = self.client.post("/api/competitor/studies/5/analyze", json={})
            self.fake._runs[first.json()["run_id"]]["status"] = "running"
            second = self.client.post("/api/competitor/studies/5/analyze", json={})

        self.assertEqual(second.json()["run_id"], first.json()["run_id"])

    def _queued_scope(self, payload):
        """The scope (and document_ids) the job actually receives for a given
        request body."""
        with patch.object(competitor_analysis, "run_analysis_job") as job, \
             patch("services.competitors.competitor_api.project_has_articles", return_value=True):
            response = self.client.post("/api/competitor/studies/5/analyze", json=payload)
        return response, job

    def test_scope_selector_reaches_the_job(self):
        """The dialog's scope picker is only meaningful if the choice survives
        the round trip to the job that actually resolves it."""
        response, job = self._queued_scope({"scope": "all"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(job.call_args[0][2], "all")

        # A fresh registry: the previous run is still "queued" (its mocked job
        # never reaches a terminal status), so without this the next POST
        # would attach to it instead of queuing a new one - correct behaviour
        # in general (see the double-click test), but not what this case means
        # to exercise.
        self.fake._runs.clear()
        response, job = self._queued_scope({})
        self.assertEqual(response.status_code, 200)
        # Absent falls back to "documents not yet analyzed", not "everything".
        self.assertEqual(job.call_args[0][2], "pending")

    def test_selected_scope_carries_its_document_ids(self):
        response, job = self._queued_scope({"scope": "selected", "document_ids": [7, 9]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(job.call_args[0][2], "selected")
        self.assertEqual(job.call_args[0][3], [7, 9])

    def test_selected_scope_without_document_ids_is_rejected(self):
        response, job = self._queued_scope({"scope": "selected"})
        self.assertEqual(response.status_code, 400)
        job.assert_not_called()

    def test_unknown_scope_is_rejected(self):
        response, job = self._queued_scope({"scope": "everything"})
        self.assertEqual(response.status_code, 400)
        job.assert_not_called()

    def test_status_404s_for_a_run_belonging_to_another_study(self):
        run = self.fake.create_run(999, "pending")
        response = self.client.get(f"/api/competitor/studies/5/analyze/{run['id']}")
        self.assertEqual(response.status_code, 404)

    def test_a_study_with_no_evidence_fails_fast_with_a_real_status(self):
        """The checks that can answer immediately stayed in the handler - moving
        them into the job would turn a 400 into a job that fails a minute later.

        With nothing uploaded, analysis has nothing to read, and "approve some
        articles first" is the actionable answer."""
        with patch("services.competitors.competitor_api.project_has_articles", return_value=False):
            response = self.client.post("/api/competitor/studies/5/analyze", json={})

        self.assertEqual(response.status_code, 400)
        # main.py normalizes every HTTPException to {"error": ...}.
        self.assertIn("Upload documents", response.json()["error"])


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
        rows = [
            {"id": 3, "name": "Study"},
        ]
        with patch("services.competitors.competitors_store.db.fetch_all", return_value=rows) as fetch_all:
            self.client.get("/api/competitor/studies")

        sql = fetch_all.call_args[0][0]
        # The rewritten query must dedupe per competitor and drop rejected
        # cards before counting - both are what made "3" the right number.
        self.assertIn("distinct on (competitor_id)", sql)
        self.assertIn("validation_status != 'rejected'", sql)
        self.assertNotIn("from competitor_findings group by project_id", sql)


if __name__ == "__main__":
    unittest.main()
