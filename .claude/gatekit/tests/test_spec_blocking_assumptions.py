"""Tests for ADR-0017 decision 5: a blocking, unconfirmed assumption fails
spec validate rather than only warning.

Design choice made here (not fully spelled out in the ADR, which names only
a "blocking (y/n)" column): the ledger table gains **two** new columns,
`blocking` and `confirmed`, rather than one. The ADR's own template rule says
"when an assumption is confirmed, do not delete the row — replace the basis
with the confirmed fact," which is a prose convention a validator cannot
check mechanically (there is no way to tell "this basis cell was rewritten to
a confirmed fact" from "this basis cell always said this" by pattern-matching
text). A second explicit `confirmed (y/n)` column makes both facts
(is this row load-bearing, has anyone confirmed it) machine-checkable without
guessing at prose. Rows without either column (pre-ADR-0017 ledgers) are
untouched — this check is additive, matching the `pains` array's own
backward-compatibility shape in test_spec_pains.py.
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

LEDGER_HEADING = "## Assumption ledger"


def prd_with_ledger_row(row: str) -> str:
    return (
        "# Widget — product requirements\n\n"
        "## Problem\n\nSomething.\n\n"
        "## Current state (measured)\n\n| Metric | Current value | Source | Measured on |\n|---|---|---|---|\n\n"
        "## Goals\n\n- A goal.\n\n"
        "## Non-goals\n\n- Not this.\n\n"
        "## Users\n\n| User | Situation | What they do today | What they need |\n|---|---|---|---|\n\n"
        "## Features\n\n### F1 — Thing\n\nDoes a thing.\n\n"
        "## Acceptance criteria\n\n- **F1** — Given x, when y, then z.\n\n"
        f"{LEDGER_HEADING}\n\n"
        "> ⚠️ Assumption 1: something unconfirmed.\n\n"
        "| # | Assumption | Basis | Impact if wrong | How to confirm | Blocking | Confirmed |\n"
        "|---|---|---|---|---|---|---|\n"
        f"{row}\n"
    )


def findings_for(report: dict, name: str = "01-prd.md") -> list:
    return [f for f in report["findings"] if f["file"] == name]


class BlockingLedgerProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-en", self.root)
        self.prd_path = self.root / "spec" / "01-prd.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, row: str) -> dict:
        self.prd_path.write_text(prd_with_ledger_row(row), encoding="utf-8")
        return spec.validate(self.root, "en")


class TestBackwardCompatibility(BlockingLedgerProject):
    def test_row_without_blocking_column_is_unaffected(self) -> None:
        report = self.write("| 1 | something unconfirmed | a guess | it breaks | ask someone |")
        blocking_msgs = [f for f in findings_for(report) if "blocking" in f["message"].lower()]
        self.assertEqual(blocking_msgs, [])


class TestBlockingUnconfirmedFails(BlockingLedgerProject):
    def test_blocking_yes_confirmed_no_fails(self) -> None:
        report = self.write("| 1 | something unconfirmed | a guess | it breaks | ask someone | y | n |")
        self.assertIn("fail", [f["verdict"] for f in findings_for(report)])

    def test_blocking_yes_confirmed_yes_passes(self) -> None:
        report = self.write("| 1 | something unconfirmed | a guess | it breaks | ask someone | y | y |")
        self.assertEqual(findings_for(report), [])

    def test_blocking_no_confirmed_no_only_warns(self) -> None:
        report = self.write("| 1 | something unconfirmed | a guess | it breaks | ask someone | n | n |")
        verdicts = [f["verdict"] for f in findings_for(report)]
        self.assertNotIn("fail", verdicts)

    def test_case_insensitive_yes_no(self) -> None:
        report = self.write("| 1 | something unconfirmed | a guess | it breaks | ask someone | Y | N |")
        self.assertIn("fail", [f["verdict"] for f in findings_for(report)])


if __name__ == "__main__":
    unittest.main()
