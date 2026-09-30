"""jobstore: the one definition of "a task is finished" and where jobs live (T20)."""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from gatekit import jobs, jobstore, spec


class TestTerminalStatesHaveOneDefinition(unittest.TestCase):
    def test_jobs_and_spec_use_the_jobstore_list(self) -> None:
        self.assertIs(jobs.TERMINAL_STATES, jobstore.TERMINAL_STATES)
        self.assertIs(spec._TERMINAL_STATES, jobstore.TERMINAL_STATES)

    def test_stopped_and_blocked_count_as_finished(self) -> None:
        for state in ("passed", "failed", "timeout", "redelegated", "stopped", "blocked"):
            self.assertIn(state, jobstore.TERMINAL_STATES)


class TestProgressFreshnessSeesEveryFinishedTask(unittest.TestCase):
    """spec._latest_job_finish feeds the "PROGRESS.md is older than the latest result"
    warning; a job that ended stopped or blocked used to be invisible to it."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)

    def write_status(self, job_id: str, task_id: str, state: str, stamp: str) -> None:
        tdir = self.root / ".gatekit" / "jobs" / job_id / "tasks" / task_id
        tdir.mkdir(parents=True)
        (tdir / "status.json").write_text(
            json.dumps({"task_id": task_id, "state": state, "finished_at": stamp}), encoding="utf-8")

    def test_a_stopped_task_is_the_latest_finish(self) -> None:
        self.write_status("20260930T010000Z-aaaa", "t1", "passed", "2026-09-30T01:00:00Z")
        self.write_status("20260930T020000Z-bbbb", "t1", "stopped", "2026-09-30T02:00:00Z")
        self.assertEqual(spec._latest_job_finish(self.root),
                         ("20260930T020000Z-bbbb", "2026-09-30T02:00:00Z"))

    def test_a_blocked_task_alone_still_counts(self) -> None:
        self.write_status("20260930T030000Z-cccc", "t2", "blocked", "2026-09-30T03:00:00Z")
        self.assertIsNotNone(spec._latest_job_finish(self.root))

    def test_a_running_task_does_not_count(self) -> None:
        self.write_status("20260930T040000Z-dddd", "t3", "running", "2026-09-30T04:00:00Z")
        self.assertIsNone(spec._latest_job_finish(self.root))


class TestJobLocation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)

    def test_no_jobs_yet(self) -> None:
        self.assertIsNone(jobstore.latest_job_id(self.root))

    def test_latest_is_the_newest_directory_with_a_job_json(self) -> None:
        for name, has_json in (("20260930T010000Z-aaaa", True),
                               ("20260930T020000Z-bbbb", True),
                               ("20260930T030000Z-cccc", False)):
            d = jobstore.job_dir(self.root, name)
            d.mkdir(parents=True)
            if has_json:
                (d / "job.json").write_text("{}", encoding="utf-8")
        self.assertEqual(jobstore.latest_job_id(self.root), "20260930T020000Z-bbbb")
        self.assertEqual(jobs.latest_job_id(self.root), "20260930T020000Z-bbbb")


if __name__ == "__main__":
    unittest.main()
