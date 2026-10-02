"""Tests for the ADR-0017 `pains` array in spec/00-discovery.md's fence.

ADR-0017 decision 1 (branch floor) and decision 2 (verdict gate): discovery
must surface at least three distinct pains before narrowing to one, and the
chosen pain's confirmed verdict (build|reuse|eliminate|unknown) must not be
eliminate or reuse before /gatekit-interview proceeds.

`pains` is additive to the existing single-problem fence shape: a record
with no `pains` key at all skips every check in this file (pre-ADR-0017
records, and `test_spec_discovery.py`'s `full_record()`, stay valid) — see
`_check_pains`'s early return in spec.py. Once a record declares `pains`,
its shape and the chosen pain's verdict are checked.
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

HEADINGS = "## 불편 목록\n\n## 고른 문제\n\n## 기한\n\n## 심화 게이트\n\n## 남은 것\n"


def base_record(**overrides) -> dict:
    record = {
        "problem": "The purchasing clerk cannot find last week's order files",
        "deadline": "4 weeks",
        "user": "Kim Yeongsu, purchasing clerk",
        "current_way": ["open mail", "download three files", "merge by eye", "send to manager"],
        "frequency_per_month": 8,
        "minutes_per_run": 40,
        "wait": "none",
        "why_chain": [
            "files are hard to find",
            "they arrive by mail with different names",
            "senders name them freely",
            "there is no shared naming rule",
            "nobody owns the naming rule",
        ],
        "failed_attempts": [
            {"tried": "shared template", "result": "failed", "why": "senders ignored it"}
        ],
        "unpassed": [],
    }
    record.update(overrides)
    return record


def three_pains(chosen_verdict="build", chosen_suggested="build") -> list:
    return [
        {
            "summary": "Purchasing clerk cannot find last week's order files",
            "chosen": True,
            "verdict_suggested": {"verdict": chosen_suggested, "why": "no existing tool covers this"},
            "verdict": chosen_verdict,
        },
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


def discovery_text(record: dict) -> str:
    return "# discovery\n\n" + HEADINGS + "\n```gatekit-discovery\n" + json.dumps(record, ensure_ascii=False) + "\n```\n"


def findings_for(report: dict, name: str = "00-discovery.md") -> list:
    return [f for f in report["findings"] if f["file"] == name]


class PainsProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-ko", self.root)
        self.path = self.root / "spec" / "00-discovery.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, record: dict) -> dict:
        self.path.write_text(discovery_text(record), encoding="utf-8")
        return spec.validate(self.root, "en")


class TestNoPainsIsBackwardCompatible(PainsProject):
    def test_record_without_pains_key_has_no_pains_findings(self) -> None:
        report = self.write(base_record())
        # No finding should mention "pains" or "verdict" at all — pre-ADR-0017
        # records are untouched by this new check.
        messages = " ".join(f["message"] for f in findings_for(report))
        self.assertNotIn("pains", messages)
        self.assertNotIn("verdict", messages)


class TestBranchFloor(PainsProject):
    def test_fewer_than_three_pains_without_waiver_fails(self) -> None:
        record = base_record(pains=three_pains()[:2])
        report = self.write(record)
        fails = [f for f in findings_for(report) if f["verdict"] == "fail"]
        self.assertTrue(fails, json.dumps(findings_for(report), indent=1))
        self.assertTrue(any("pains" in f["message"] or "3" in f["message"] for f in fails))

    def test_two_pains_with_waiver_only_warns(self) -> None:
        record = base_record(pains=three_pains()[:2], pain_floor_waived=True)
        report = self.write(record)
        self.assertNotIn("fail", [f["verdict"] for f in findings_for(report) if "pain" in f["message"].lower()])

    def test_three_pains_satisfies_the_floor(self) -> None:
        record = base_record(pains=three_pains())
        report = self.write(record)
        floor_findings = [f for f in findings_for(report) if "at least three" in f["message"].lower() or "최소 3" in f["message"]]
        self.assertEqual(floor_findings, [])

    def test_pains_not_a_list_fails(self) -> None:
        record = base_record(pains="not-a-list")
        report = self.write(record)
        self.assertIn("fail", [f["verdict"] for f in findings_for(report)])


class TestVerdictShape(PainsProject):
    def test_missing_chosen_pain_fails(self) -> None:
        pains = three_pains()
        for p in pains:
            p["chosen"] = False
        record = base_record(pains=pains)
        report = self.write(record)
        self.assertIn("fail", [f["verdict"] for f in findings_for(report)])

    def test_two_chosen_pains_fails(self) -> None:
        pains = three_pains()
        pains[1]["chosen"] = True
        record = base_record(pains=pains)
        report = self.write(record)
        self.assertIn("fail", [f["verdict"] for f in findings_for(report)])

    def test_unknown_verdict_enum_value_fails(self) -> None:
        pains = three_pains()
        pains[0]["verdict"] = "definitely-build-this"
        record = base_record(pains=pains)
        report = self.write(record)
        self.assertIn("fail", [f["verdict"] for f in findings_for(report)])

    def test_verdict_suggested_without_why_fails(self) -> None:
        pains = three_pains()
        pains[0]["verdict_suggested"] = {"verdict": "build"}
        record = base_record(pains=pains)
        report = self.write(record)
        self.assertIn("fail", [f["verdict"] for f in findings_for(report)])


class TestVerdictGate(PainsProject):
    """ADR-0017 decision 2: eliminate/reuse on the *chosen* pain blocks
    progression to interview; unknown never blocks (blocking it would make
    staying undecided the strategy that avoids the gate)."""

    def test_chosen_pain_eliminate_fails(self) -> None:
        record = base_record(pains=three_pains(chosen_verdict="eliminate", chosen_suggested="eliminate"))
        report = self.write(record)
        self.assertIn("fail", [f["verdict"] for f in findings_for(report)])

    def test_chosen_pain_reuse_fails(self) -> None:
        record = base_record(pains=three_pains(chosen_verdict="reuse", chosen_suggested="reuse"))
        report = self.write(record)
        self.assertIn("fail", [f["verdict"] for f in findings_for(report)])

    def test_chosen_pain_build_passes(self) -> None:
        record = base_record(pains=three_pains(chosen_verdict="build", chosen_suggested="build"))
        report = self.write(record)
        self.assertEqual(findings_for(report), [])

    def test_chosen_pain_unknown_does_not_block(self) -> None:
        """Unknown is deliberately not blocking — see spec.py's comment on why:
        blocking on "not sure yet" would reward staying undecided."""
        record = base_record(pains=three_pains(chosen_verdict="unknown", chosen_suggested="unknown"))
        report = self.write(record)
        self.assertNotIn("fail", [f["verdict"] for f in findings_for(report)])

    def test_chosen_pain_verdict_not_yet_confirmed_warns_not_fails(self) -> None:
        """verdict_suggested alone (verdict still null) is a warn: the
        interviewer proposed, but the user has not confirmed yet — this is
        exactly the gap Assumption 4 of gk-trial2 fell into (a mapping
        decided without ever being posed as a question), so it must be
        visible, but it is not yet a known-bad verdict like eliminate/reuse."""
        pains = three_pains(chosen_verdict=None, chosen_suggested="build")
        pains[0]["verdict"] = None
        record = base_record(pains=pains)
        report = self.write(record)
        verdicts = [f["verdict"] for f in findings_for(report)]
        self.assertIn("warn", verdicts)
        self.assertNotIn("fail", verdicts)


if __name__ == "__main__":
    unittest.main()
