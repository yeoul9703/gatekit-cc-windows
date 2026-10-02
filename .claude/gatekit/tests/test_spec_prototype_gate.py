"""Tests for ADR-0017 decision 4: a confirmed live-prototype record is
required in spec/02-screens.md before /gatekit-tasks may proceed.

The confirmation is a line of prose in 02-screens.md (parallel to how the
assumption ledger's inline markers are prose the validator scans for), never
a hash-anchored approval like 05-gate.md's — the prototype is revised
in-loop until confirmed, unlike the gate file's one-shot approve/expire
shape, so there is nothing to pin a hash to that would not immediately go
stale on the next accepted revision.
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


class PrototypeGateProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-ko", self.root)
        self.screens_path = self.root / "spec" / "02-screens.md"
        # The canonical fixture now carries its own confirmation line (it
        # represents a project already past this gate) — strip it so tests
        # here start from the pre-confirmation state they mean to exercise.
        text = self.screens_path.read_text(encoding="utf-8")
        confirmed = "\n\n프로토타입 확정 2026-09-19\n"
        self.assertIn(confirmed, text)
        text = text.replace(confirmed, "\n")
        self.screens_path.write_text(text, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestPrototypeConfirmation(PrototypeGateProject):
    def test_screens_without_confirmation_line_fails(self) -> None:
        report = spec.validate(self.root, "en")
        self.assertIn("fail", [f["verdict"] for f in findings_for(report, "04-tasks.md")])

    def test_screens_with_confirmation_line_passes(self) -> None:
        text = self.screens_path.read_text(encoding="utf-8")
        text += "\nPrototype confirmed 2026-09-19\n"
        self.screens_path.write_text(text, encoding="utf-8")
        report = spec.validate(self.root, "en")
        messages = [f["message"] for f in findings_for(report, "04-tasks.md")]
        self.assertFalse(any("prototype" in m.lower() for m in messages))

    def test_korean_confirmation_line_is_recognised(self) -> None:
        text = self.screens_path.read_text(encoding="utf-8")
        text += "\n프로토타입 확정 2026-09-19\n"
        self.screens_path.write_text(text, encoding="utf-8")
        report = spec.validate(self.root, "ko")
        messages = [f["message"] for f in findings_for(report, "04-tasks.md")]
        self.assertFalse(any("프로토타입" in m for m in messages))

    def test_no_screens_file_does_not_double_report(self) -> None:
        # decision 3's screens_required already covers this gap; decision 4's
        # check must not also fire when there is no screens file to confirm.
        self.screens_path.unlink()
        report = spec.validate(self.root, "en")
        messages = [f["message"] for f in findings_for(report, "04-tasks.md")]
        prototype_msgs = [m for m in messages if "prototype" in m.lower()]
        self.assertEqual(prototype_msgs, [])

    def test_non_ui_project_does_not_need_a_prototype(self) -> None:
        prd_path = self.root / "spec" / "01-prd.md"
        text = prd_path.read_text(encoding="utf-8")
        non_goals = "## 목표가 아닌 것\n\n- 공유 기능은 이번 범위가 아니다."
        self.assertIn(non_goals, text)
        text = text.replace(non_goals, non_goals + "\n- [non-ui] 화면이 없는 CLI 도구다.")
        prd_path.write_text(text, encoding="utf-8")
        self.screens_path.unlink()
        report = spec.validate(self.root, "en")
        messages = [f["message"] for f in findings_for(report, "04-tasks.md")]
        self.assertFalse(any("prototype" in m.lower() for m in messages))


if __name__ == "__main__":
    unittest.main()
