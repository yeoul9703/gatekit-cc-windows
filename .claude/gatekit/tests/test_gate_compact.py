"""Tests for gates/compact.py — ADR-0013 decision 1a.

Host execution means a build lives in one session, so a compaction is normal
rather than exceptional. Everything the build must not forget is already on
disk; this hook makes that explicit by stamping the state into PROGRESS.md
before the summary is taken.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import jobs  # noqa: E402
from gatekit.gates import compact as compact_gate  # noqa: E402
from tests import isolation  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "compact.py"


class CompactProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def event(self) -> dict:
        return {"session_id": "s1", "hook_event_name": "PreCompact",
                "cwd": str(self.root)}

    def make_job(self, states: dict) -> str:
        job_id = jobs.new_job_id()
        jdir = jobs.job_dir(self.root, job_id)
        (jdir / "tasks").mkdir(parents=True)
        jobs.write_json(jdir / "job.json", {
            "version": 1, "job_id": job_id, "started_at": jobs._now(),
            "tasks": list(states)})
        for task_id, state in states.items():
            tdir = jdir / "tasks" / task_id
            tdir.mkdir(parents=True)
            jobs.write_json(tdir / "status.json", {
                "task_id": task_id, "state": state,
                "gates_passed": 1 if state == "passed" else 0,
                "gates_total": 1, "detail": "%s detail" % state})
        return job_id

    def progress(self) -> str:
        path = self.root / "spec" / "PROGRESS.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""


class TestStamping(CompactProject):
    def test_it_records_every_task_state(self) -> None:
        self.make_job({"a": "passed", "b": "failed", "c": "queued"})
        compact_gate.handle(self.event())
        text = self.progress()
        for task in ("a", "b", "c"):
            self.assertIn(task, text)
        self.assertIn("passed", text)
        self.assertIn("failed", text)

    def test_it_names_the_job(self) -> None:
        job_id = self.make_job({"a": "passed"})
        compact_gate.handle(self.event())
        self.assertIn(job_id, self.progress())

    def test_it_creates_progress_when_absent(self) -> None:
        self.make_job({"a": "passed"})
        self.assertFalse((self.root / "spec" / "PROGRESS.md").exists())
        compact_gate.handle(self.event())
        self.assertTrue((self.root / "spec" / "PROGRESS.md").is_file())

    def test_it_appends_without_destroying_existing_content(self) -> None:
        (self.root / "spec" / "PROGRESS.md").write_text(
            "# 진행 상황\n\nSTATUS: in-progress\n\n## 현재 상태\n\n사람이 쓴 문단.\n",
            encoding="utf-8")
        self.make_job({"a": "passed"})
        compact_gate.handle(self.event())
        text = self.progress()
        self.assertIn("사람이 쓴 문단", text)
        self.assertIn("## 현재 상태", text)

    def test_a_second_compaction_replaces_the_first_stamp(self) -> None:
        self.make_job({"a": "passed"})
        compact_gate.handle(self.event())
        first = self.progress()
        compact_gate.handle(self.event())
        second = self.progress()
        self.assertEqual(second.count(compact_gate.SECTION_MARKER), 1)
        self.assertNotEqual(first, "")

    def test_no_job_writes_nothing(self) -> None:
        compact_gate.handle(self.event())
        self.assertEqual(self.progress(), "")

    def test_a_finished_job_is_still_stamped(self) -> None:
        job_id = self.make_job({"a": "passed"})
        jdir = jobs.job_dir(self.root, job_id)
        job = jobs.read_json(jdir / "job.json", {})
        job["finished_at"] = jobs._now()
        jobs.write_json(jdir / "job.json", job)
        compact_gate.handle(self.event())
        self.assertIn(job_id, self.progress())

    def test_it_never_blocks(self) -> None:
        self.make_job({"a": "passed"})
        self.assertIsNone((compact_gate.handle(self.event()) or {}).get("decision"))


class TestRobustness(CompactProject):
    def test_an_unwritable_spec_dir_does_not_raise(self) -> None:
        self.make_job({"a": "passed"})
        (self.root / "spec").chmod(0o500)
        try:
            compact_gate.handle(self.event())   # must not raise
        finally:
            (self.root / "spec").chmod(0o700)

    def test_a_corrupt_status_file_is_skipped(self) -> None:
        job_id = self.make_job({"a": "passed", "b": "failed"})
        (jobs.job_dir(self.root, job_id) / "tasks" / "b" / "status.json").write_text(
            "{not json", encoding="utf-8")
        compact_gate.handle(self.event())
        self.assertIn("a", self.progress())

    def test_subprocess_exits_zero(self) -> None:
        self.make_job({"a": "passed"})
        proc = isolation.run_gate(
            [sys.executable, str(GATE_SCRIPT)], cwd=self.root,
            input=json.dumps(self.event()).encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("a", self.progress())

    def test_malformed_stdin_exits_zero(self) -> None:
        # No event means no cwd: the gate reads the jobs of its working directory's project.
        proc = isolation.run_gate(
            [sys.executable, str(GATE_SCRIPT)], cwd=self.root,
            input=b"not json", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.progress(), "")


if __name__ == "__main__":
    unittest.main()


class TestDoesNotBreakValidation(CompactProject):
    """The stamp must not make `spec validate` reject PROGRESS.md.

    Its heading is an extra one: `spec validate` asks for the canonical
    headings and allows any other, so the stamp adds no finding.
    """

    def test_a_template_progress_still_validates(self) -> None:
        from gatekit import spec
        template = (pathlib.Path(__file__).resolve().parents[2]
                    / "skills" / "gatekit-build" / "assets" / "PROGRESS.md")
        (self.root / "spec" / "PROGRESS.md").write_text(
            template.read_text(encoding="utf-8"), encoding="utf-8")
        self.make_job({"a": "passed"})
        before = [f for f in spec.validate(self.root)["findings"]
                  if f["file"] == "PROGRESS.md"]
        compact_gate.handle(self.event())
        after = [f for f in spec.validate(self.root)["findings"]
                 if f["file"] == "PROGRESS.md"]
        self.assertEqual(len(before), len(after))

    def test_the_heading_is_not_a_canonical_one(self) -> None:
        from gatekit import spec
        canonical = spec.canonical_headings("PROGRESS.md")
        self.assertTrue(canonical)
        self.assertNotIn("## Build state at last compaction", canonical)
