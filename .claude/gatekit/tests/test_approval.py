"""Tests for gatekit.approval — hash-anchored approvals."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import approval


class TempProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        self.gate = self.root / "spec" / "05-gate.md"
        self.gate.write_text("# Gate\ncriteria here\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def approvals(self) -> dict:
        return json.loads((self.root / ".gatekit" / "approvals.json").read_text(encoding="utf-8"))


class TestSha256File(TempProject):
    def test_matches_hashlib(self) -> None:
        expected = hashlib.sha256(self.gate.read_bytes()).hexdigest()
        self.assertEqual(approval.sha256_file(self.gate), expected)

    def test_missing_file_returns_empty_string(self) -> None:
        self.assertEqual(approval.sha256_file(self.root / "nope.md"), "")

    def test_directory_returns_empty_string(self) -> None:
        self.assertEqual(approval.sha256_file(self.root / "spec"), "")

    def test_changes_with_content(self) -> None:
        before = approval.sha256_file(self.gate)
        self.gate.write_text("different\n", encoding="utf-8")
        self.assertNotEqual(before, approval.sha256_file(self.gate))


class TestCheck(TempProject):
    def test_no_approvals_file_is_unverified(self) -> None:
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "unverified")

    def test_after_approve_is_ok(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "ok")

    def test_modified_file_is_fail_not_unverified(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        self.gate.write_text("# Gate\nchanged after approval\n", encoding="utf-8")
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "fail")

    def test_unapproved_target_is_unverified(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        self.assertEqual(approval.check(self.root, "spec/01-prd.md"), "unverified")

    def test_missing_file_with_approval_is_fail(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        self.gate.unlink()
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "fail")

    def test_corrupt_approvals_file_is_unverified(self) -> None:
        (self.root / ".gatekit" / "approvals.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "unverified")

    def test_non_object_approvals_file_is_unverified(self) -> None:
        (self.root / ".gatekit" / "approvals.json").write_text("[]", encoding="utf-8")
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "unverified")

    def test_path_separators_normalized(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        self.assertEqual(approval.check(self.root, "./spec/05-gate.md"), "ok")

    def test_re_approve_after_edit_returns_ok(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        self.gate.write_text("v2\n", encoding="utf-8")
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "fail")
        approval.approve(self.root, "spec/05-gate.md")
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "ok")


class TestApprove(TempProject):
    def test_records_hash_and_metadata(self) -> None:
        entry = approval.approve(self.root, "spec/05-gate.md", note="looks good")
        self.assertEqual(entry["target"], "spec/05-gate.md")
        self.assertEqual(entry["sha256"], approval.sha256_file(self.gate))
        self.assertEqual(entry["approved_by"], "user")
        self.assertEqual(entry["note"], "looks good")
        self.assertIn("approved_at", entry)

    def test_writes_versioned_file(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        data = self.approvals()
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["approvals"]), 1)

    def test_re_approving_replaces_not_appends(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        self.gate.write_text("v2\n", encoding="utf-8")
        approval.approve(self.root, "spec/05-gate.md")
        entries = self.approvals()["approvals"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["sha256"], approval.sha256_file(self.gate))

    def test_multiple_targets_coexist(self) -> None:
        (self.root / "spec" / "01-prd.md").write_text("prd\n", encoding="utf-8")
        approval.approve(self.root, "spec/05-gate.md")
        approval.approve(self.root, "spec/01-prd.md")
        self.assertEqual(len(self.approvals()["approvals"]), 2)

    def test_approving_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            approval.approve(self.root, "spec/nope.md")

    def test_never_overwrites_the_target_file(self) -> None:
        before = self.gate.read_bytes()
        approval.approve(self.root, "spec/05-gate.md")
        self.assertEqual(self.gate.read_bytes(), before)

    def test_custom_approver(self) -> None:
        entry = approval.approve(self.root, "spec/05-gate.md", by="ci")
        self.assertEqual(entry["approved_by"], "ci")

    def test_preserves_unrelated_existing_entries(self) -> None:
        (self.root / ".gatekit" / "approvals.json").write_text(
            json.dumps(
                {"version": 1, "approvals": [{"target": "other.md", "sha256": "abc"}]}
            ),
            encoding="utf-8",
        )
        approval.approve(self.root, "spec/05-gate.md")
        targets = {e["target"] for e in self.approvals()["approvals"]}
        self.assertEqual(targets, {"other.md", "spec/05-gate.md"})


class TestRun(TempProject):
    def _run(self, argv: "list[str]") -> "tuple[int, str]":
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = approval.run(argv)
        return rc, out.getvalue().strip()

    def test_check_prints_unverified(self) -> None:
        rc, out = self._run(["check", "spec/05-gate.md", "--root", str(self.root)])
        self.assertEqual(out, "unverified")
        self.assertNotEqual(rc, 0)

    def test_approve_then_check_prints_ok(self) -> None:
        rc, _ = self._run(["spec/05-gate.md", "--root", str(self.root)])
        self.assertEqual(rc, 0)
        rc, out = self._run(["check", "spec/05-gate.md", "--root", str(self.root)])
        self.assertEqual(out, "ok")
        self.assertEqual(rc, 0)

    def test_check_stale_prints_fail(self) -> None:
        self._run(["spec/05-gate.md", "--root", str(self.root)])
        self.gate.write_text("changed\n", encoding="utf-8")
        rc, out = self._run(["check", "spec/05-gate.md", "--root", str(self.root)])
        self.assertEqual(out, "fail")
        self.assertNotEqual(rc, 0)

    def test_list_shows_targets(self) -> None:
        self._run(["spec/05-gate.md", "--root", str(self.root)])
        rc, out = self._run(["list", "--root", str(self.root)])
        self.assertEqual(rc, 0)
        self.assertIn("spec/05-gate.md", out)

    def test_approve_missing_file_is_nonzero(self) -> None:
        rc, _ = self._run(["spec/nope.md", "--root", str(self.root)])
        self.assertNotEqual(rc, 0)

    def test_no_args_is_nonzero(self) -> None:
        rc, _ = self._run([])
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
