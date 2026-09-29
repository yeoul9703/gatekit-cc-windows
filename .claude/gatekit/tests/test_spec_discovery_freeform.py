"""Tests for the free-form discovery shape (found 2026-09-20, after ADR-0017
decisions 7-11 ran against a real project — the owner rejected the six
deepening gates' fixed-slot, one-at-a-time, progress-counted process as
"허접함" next to grill-me and ai-dev-pm's free-ranging conversations).

The gate fields themselves (who, how today, how often, why, what was tried)
are still useful information — only the scripted, top-level, single-problem
process of filling them is gone. They now live inside whichever pain in
`pains` the free conversation actually deepened (`chosen: true`), summarized
post-hoc rather than filled slot-by-slot during the conversation.

This is additive: a record with gate fields at the top level (the pre-
2026-09-20 shape) validates exactly as `test_spec_discovery.py` already
covers. These tests cover the new shape — gate fields inside the chosen
pain — plus `insights_count`, the uncapped, mechanical "how many distinct
branches did this conversation actually surface" record ADR-0017 borrows
from grill-me's decision-branch count (a floor, never a ceiling).
"""
from __future__ import annotations

import json
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
EN_HEADINGS = "## Pain list\n\n## Chosen problem\n\n## Deadline\n\n## Deepening gates\n\n## Open items\n"


def pain_with_gates(**gate_overrides) -> dict:
    pain = {
        "summary": "The purchasing clerk cannot find last week's order files",
        "chosen": True,
        "verdict_suggested": {"verdict": "build", "why": "no existing tool covers this"},
        "verdict": "build",
        "user": "Kim Yeongsu, purchasing clerk",
        "current_way": ["open mail", "download three files", "merge by eye", "send to manager"],
        "frequency_per_month": 8,
        "minutes_per_run": 40,
        "why_chain": [
            "files are hard to find",
            "they arrive by mail with different names",
            "senders name them freely",
            "there is no shared naming rule",
        ],
        "failed_attempts": [{"tried": "shared template", "result": "failed", "why": "senders ignored it"}],
    }
    pain.update(gate_overrides)
    return pain


def other_pains() -> list:
    return [
        {
            "summary": "Sales team re-types the same customer address every order",
            "chosen": False,
            "verdict_suggested": {"verdict": "reuse", "why": "CRM already stores addresses"},
            "verdict": None,
        },
        {
            "summary": "Warehouse logs shipment counts on paper",
            "chosen": False,
            "verdict_suggested": {"verdict": "unknown", "why": "not enough information yet"},
            "verdict": None,
        },
    ]


def record_with(chosen_pain: dict, **top_level) -> dict:
    record = {"pains": [chosen_pain] + other_pains(), "deadline": "4 weeks"}
    record.update(top_level)
    return record


def discovery_text(record: dict) -> str:
    return "# discovery\n\n" + EN_HEADINGS + "\n```gatekit-discovery\n" + json.dumps(record, ensure_ascii=False) + "\n```\n"


def findings_for(report: dict, name: str = "00-discovery.md") -> list:
    return [f for f in report["findings"] if f["file"] == name]


class FreeformProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-en", self.root)
        self.path = self.root / "spec" / "00-discovery.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, record: dict) -> dict:
        self.path.write_text(discovery_text(record), encoding="utf-8")
        return spec.validate(self.root, "en")


class TestGatesInsideChosenPain(FreeformProject):
    def test_complete_gates_inside_chosen_pain_has_no_gate_findings(self) -> None:
        report = self.write(record_with(pain_with_gates()))
        gate_findings = [f for f in findings_for(report) if f["message"].startswith(("Deepening gate", "심화"))]
        self.assertEqual(gate_findings, [])

    def test_no_top_level_problem_required_once_pains_exist(self) -> None:
        """The pre-pains shape required a top-level `problem`; once pains
        exist, the chosen pain's own `summary` plays that role instead."""
        record = record_with(pain_with_gates())
        self.assertNotIn("problem", record)
        report = self.write(record)
        self.assertNotIn("fail", [f["verdict"] for f in findings_for(report)])

    def test_short_current_way_inside_pain_warns(self) -> None:
        report = self.write(record_with(pain_with_gates(current_way=["do it manually"])))
        warns = [f for f in findings_for(report) if f["verdict"] == "warn" and "current_way" in f["message"]]
        self.assertEqual(len(warns), 1)

    def test_missing_why_chain_inside_pain_warns(self) -> None:
        pain = pain_with_gates()
        del pain["why_chain"]
        report = self.write(record_with(pain))
        warns = [f for f in findings_for(report) if f["verdict"] == "warn" and "why_chain" in f["message"]]
        self.assertEqual(len(warns), 1)

    def test_top_level_gate_fields_are_not_consulted_when_pain_has_its_own(self) -> None:
        """A stray top-level `user` must not paper over a missing one inside
        the chosen pain — the chosen pain is the source of truth once it
        carries any gate field at all."""
        pain = pain_with_gates()
        del pain["user"]
        report = self.write(record_with(pain, user="stray top-level value"))
        warns = [f for f in findings_for(report) if f["verdict"] == "warn" and "user" in f["message"]]
        self.assertEqual(len(warns), 1)


class TestInsightsCount(FreeformProject):
    def test_absent_insights_count_is_silent(self) -> None:
        report = self.write(record_with(pain_with_gates()))
        self.assertEqual([f for f in findings_for(report) if "insights_count" in f["message"]], [])

    def test_high_insights_count_passes(self) -> None:
        report = self.write(record_with(pain_with_gates(), insights_count=14))
        self.assertEqual([f for f in findings_for(report) if "insights_count" in f["message"]], [])

    def test_low_insights_count_warns_not_fails(self) -> None:
        report = self.write(record_with(pain_with_gates(), insights_count=1))
        findings = [f for f in findings_for(report) if "insights_count" in f["message"]]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["verdict"], "warn")

    def test_non_numeric_insights_count_fails(self) -> None:
        report = self.write(record_with(pain_with_gates(), insights_count="a lot"))
        findings = [f for f in findings_for(report) if "insights_count" in f["message"]]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["verdict"], "fail")

    def test_no_ceiling_exists_for_insights_count(self) -> None:
        """The one property this whole feature exists to guarantee: there is
        no upper bound anywhere in the validator for insights_count."""
        report = self.write(record_with(pain_with_gates(), insights_count=500))
        self.assertEqual([f for f in findings_for(report) if "insights_count" in f["message"]], [])
        self.assertNotIn("fail", [f["verdict"] for f in findings_for(report)])


if __name__ == "__main__":
    unittest.main()
