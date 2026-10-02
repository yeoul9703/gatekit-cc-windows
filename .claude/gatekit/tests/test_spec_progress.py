"""spec validate flags a PROGRESS.md that is older than the latest job result."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest

PLUGIN_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from gatekit import spec  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "spec"


class ProgressProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-ko", self.root)
        (self.root / ".gatekit").mkdir(exist_ok=True)
        self.progress = self.root / "spec" / "PROGRESS.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def job(self, finished_iso: str, state: str = "passed") -> None:
        tdir = self.root / ".gatekit" / "jobs" / "job-1" / "tasks" / "t1"
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "status.json").write_text(
            json.dumps({"task_id": "t1", "state": state, "finished_at": finished_iso, "updated_at": finished_iso}),
            encoding="utf-8",
        )

    def progress_findings(self):
        return [f for f in spec.validate(self.root, "en")["findings"] if f["file"] == "PROGRESS.md"]

    def test_no_jobs_no_finding(self) -> None:
        self.assertEqual(self.progress_findings(), [])

    def test_progress_newer_than_job_is_fine(self) -> None:
        self.job("2000-01-01T00:00:00Z")
        self.assertEqual(self.progress_findings(), [])

    def test_progress_older_than_job_warns(self) -> None:
        old = time.time() - 3600
        os.utime(self.progress, (old, old))
        self.job(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        findings = self.progress_findings()
        self.assertEqual([f["verdict"] for f in findings], ["warn"])
        self.assertIn("job", findings[0]["message"])

    def test_running_job_does_not_count(self) -> None:
        old = time.time() - 3600
        os.utime(self.progress, (old, old))
        self.job(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), state="running")
        self.assertEqual(self.progress_findings(), [])

    def test_missing_progress_is_the_existing_warn_only(self) -> None:
        self.progress.unlink()
        self.job(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        findings = self.progress_findings()
        self.assertEqual(len(findings), 1)


if __name__ == "__main__":
    unittest.main()
