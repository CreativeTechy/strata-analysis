"""Deleting an analysis run.

The contract: deleting a run removes the *record of a run* - the row, its
per-document breakdown and its per-article snapshots - so it stops being a
comparison point on the dashboard. It does not roll the article corpus back.
An article whose analysis came from the deleted run keeps that analysis; it
only loses the attribution (articles.pipeline_run_id is ON DELETE SET NULL).
"""

import unittest
from unittest.mock import patch

from services.pipeline import pipeline_runs


class DeletePipelineRunTests(unittest.TestCase):
    def _patched(self, run, executed):
        return (
            patch.object(pipeline_runs.config, "DATABASE_URL", "postgresql://test"),
            patch.object(pipeline_runs, "get_pipeline_run", return_value=run),
            patch.object(pipeline_runs.db, "execute", side_effect=lambda sql, params: executed.append((sql, params))),
        )

    def test_terminal_run_is_deleted_by_id(self):
        executed = []
        run = {"id": "run-1", "status": "success", "sequence_number": 2, "project_id": 3}
        for patcher in self._patched(run, executed):
            patcher.start()
        try:
            deleted = pipeline_runs.delete_pipeline_run("run-1")
        finally:
            patch.stopall()

        self.assertEqual(deleted, run)
        sql, params = executed[0]
        self.assertIn("delete from pipeline_runs", sql)
        self.assertEqual(params, ("run-1",))

    def test_cancelled_and_failed_runs_are_deletable(self):
        """Terminal is terminal - only queued/running is still in flight."""
        for status in ("success", "failed", "cancelled"):
            executed = []
            run = {"id": "run-1", "status": status, "project_id": 3}
            for patcher in self._patched(run, executed):
                patcher.start()
            try:
                self.assertEqual(pipeline_runs.delete_pipeline_run("run-1"), run)
            finally:
                patch.stopall()
            self.assertEqual(len(executed), 1, f"{status} should have been deleted")

    def test_in_flight_run_is_refused_rather_than_stopped_implicitly(self):
        """Its worker thread is still writing progress into that row; deleting it
        out from under the run would have the worker updating a row that no
        longer exists."""
        for status in ("queued", "running"):
            executed = []
            run = {"id": "run-1", "status": status, "project_id": 3}
            for patcher in self._patched(run, executed):
                patcher.start()
            try:
                with self.assertRaises(ValueError) as caught:
                    pipeline_runs.delete_pipeline_run("run-1")
                self.assertIn(status, str(caught.exception))
            finally:
                patch.stopall()
            self.assertEqual(executed, [], f"{status} run must not be deleted")

    def test_unknown_run_returns_none_and_deletes_nothing(self):
        executed = []
        for patcher in self._patched(None, executed):
            patcher.start()
        try:
            self.assertIsNone(pipeline_runs.delete_pipeline_run("nope"))
        finally:
            patch.stopall()
        self.assertEqual(executed, [])

    def test_no_run_id_is_a_no_op(self):
        with patch.object(pipeline_runs.config, "DATABASE_URL", "postgresql://test"), \
             patch.object(pipeline_runs.db, "execute") as execute:
            self.assertIsNone(pipeline_runs.delete_pipeline_run(""))
            self.assertIsNone(pipeline_runs.delete_pipeline_run(None))
        execute.assert_not_called()

    def test_delete_targets_only_the_run_table(self):
        """pipeline_run_documents and article_analyses come away via ON DELETE
        CASCADE, and articles via ON DELETE SET NULL - the corpus is never
        touched by an explicit statement here."""
        executed = []
        run = {"id": "run-1", "status": "success", "project_id": 3}
        for patcher in self._patched(run, executed):
            patcher.start()
        try:
            pipeline_runs.delete_pipeline_run("run-1")
        finally:
            patch.stopall()

        self.assertEqual(len(executed), 1)
        self.assertNotIn("articles", executed[0][0])


if __name__ == "__main__":
    unittest.main()
