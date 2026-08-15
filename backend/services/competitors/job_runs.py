"""In-memory registry for one-shot background jobs the user watches live.

Competitor discovery and competitor analysis both queue a FastAPI
BackgroundTask that can run for minutes - well past any gateway timeout - and
both stream progress lines the UI polls for while it runs. This is the
bookkeeping both need: a process-local dict of runs guarded by one lock, with
an append-only log per run.

Deliberately in-process rather than Postgres. These are one-shot steps a user
is sitting in front of, not durable scheduled work like the scrape pipeline
(which does persist, via `pipeline_runs`) - if the backend restarts mid-run
there is nothing worth resuming, the UI just needs to let the user retry.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

ACTIVE_STATUSES = ("queued", "running")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRegistry:
    """One namespace of runs - discovery, analysis - keyed by run id.

    Every method is safe to call from worker threads: the pools inside a job
    append progress lines concurrently while the request thread serving the
    status endpoint reads them.
    """

    def __init__(self, queued_message: str):
        self._lock = threading.Lock()
        self._runs: dict[str, dict] = {}
        self._queued_message = queued_message

    def create(self, project_id: int, **extra) -> str:
        run_id = uuid.uuid4().hex
        with self._lock:
            self._runs[run_id] = {
                "run_id": run_id,
                "project_id": project_id,
                "status": "queued",
                "stage": "queued",
                "message": self._queued_message,
                "error": None,
                "logs": [],
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                **extra,
            }
        return run_id

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return None
            copy = dict(run)
            # A plain dict(run) still shares the same `logs` list object with
            # the live run - copy it too so a response being serialized never
            # reads a list a worker thread is concurrently appending to.
            copy["logs"] = list(run.get("logs") or [])
            return copy

    def active_for_project(self, project_id: int) -> dict | None:
        with self._lock:
            for run in self._runs.values():
                if run["project_id"] == project_id and run["status"] in ACTIVE_STATUSES:
                    return dict(run)
        return None

    def update(self, run_id: str, **fields) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                run.update(fields, updated_at=_now_iso())

    def append_log(self, run_id: str, message: str) -> None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                run.setdefault("logs", []).append({"ts": _now_iso(), "message": message})
                run["updated_at"] = _now_iso()

    def logger(self, run_id: str):
        """A one-argument `log(message)` to hand to code that shouldn't have to
        know about run ids - the analysis functions take one so they can be
        called just as well from the CLI/seed path with no run at all."""
        return lambda message: self.append_log(run_id, message)
