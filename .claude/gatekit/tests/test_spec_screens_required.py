"""Tests for ADR-0017 decision 3: spec/02-screens.md becomes a required gate
before /gatekit-tasks for any PRD whose features imply a user-facing screen.

Detection reuses the same signal `tasks.md` Step 2 already uses informally
("the surface a user touches"): a PRD is UI-bearing unless it carries an
explicit non-UI marker in its Non-goals section, `[non-ui]`, recorded by
/gatekit-interview for a pure-CLI or pure-library spec. Defaulting to
UI-bearing (rather than scanning feature prose for keywords) keeps the check
deterministic — a prose heuristic over feature text would be exactly the kind
of guess CLAUDE.md warns against for a gate.
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

PLUGIN_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from gatekit import spec  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "spec"


def findings_for(report: dict, name: str) -> list:
    return [f for f in report["findings"] if f["file"] == name]


class ScreensRequiredProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-ko", self.root)
        self.screens_path = self.root / "spec" / "02-screens.md"
        self.prd_path = self.root / "spec" / "01-prd.md"
        self.tasks_path = self.root / "spec" / "04-tasks.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestUiImplied(ScreensRequiredProject):
    def test_missing_screens_with_ui_bearing_prd_and_tasks_fails(self) -> None:
        self.screens_path.unlink()
        report = spec.validate(self.root, "en")
        self.assertIn("fail", [f["verdict"] for f in findings_for(report, "04-tasks.md")])

    def test_non_ui_marker_in_prd_exempts_the_project(self) -> None:
        self.screens_path.unlink()
        text = self.prd_path.read_text(encoding="utf-8")
        non_goals = "## 목표가 아닌 것\n\n- 공유 기능은 이번 범위가 아니다."
        self.assertIn(non_goals, text)
        text = text.replace(non_goals, non_goals + "\n- [non-ui] 화면이 없는 CLI 도구다.")
        self.prd_path.write_text(text, encoding="utf-8")
        report = spec.validate(self.root, "en")
        messages = " ".join(f["message"] for f in findings_for(report, "04-tasks.md"))
        self.assertNotIn("02-screens.md", messages)

    def test_present_screens_file_produces_no_such_finding(self) -> None:
        report = spec.validate(self.root, "en")
        messages = " ".join(f["message"] for f in findings_for(report, "04-tasks.md"))
        self.assertNotIn("requires spec/02-screens.md", messages.lower().replace("requires", "requires"))

    def test_no_prd_yet_does_not_trigger_this_check(self) -> None:
        # 01-prd.md missing entirely is already its own required-file failure;
        # this check must not also fire and double-report the same gap.
        self.screens_path.unlink()
        self.prd_path.unlink()
        report = spec.validate(self.root, "en")
        messages = [f["message"] for f in findings_for(report, "04-tasks.md")]
        self.assertFalse(any("02-screens.md" in m for m in messages))


if __name__ == "__main__":
    unittest.main()
