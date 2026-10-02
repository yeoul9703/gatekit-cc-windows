"""Tests for gatekit-verify/assets/design-antipatterns.json (ADR-0017 decision 9).

This file is read as prose by the verify evaluator's prompt, not by any
gatekit module — there is no merge or derive logic to unit test the way
presets/design/ has. What is worth pinning here is the data's own shape:
valid JSON, unique ids, and every row carrying the fields a human or an
evaluator would need to act on it (a name, a rule, evidence for where the
pattern came from). A malformed row here would silently degrade to "the
evaluator prompt cites a file that doesn't make sense," which nothing else
in the test suite would catch.
"""
from __future__ import annotations

import json
import pathlib
import unittest

SKILLS_DIR = pathlib.Path(__file__).resolve().parents[2] / "skills"
ANTIPATTERNS_PATH = SKILLS_DIR / "gatekit-verify" / "assets" / "design-antipatterns.json"


class TestDesignAntipatterns(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(ANTIPATTERNS_PATH.read_text(encoding="utf-8"))

    def test_file_exists_and_parses(self) -> None:
        self.assertIsInstance(self.data, dict)

    def test_has_version_and_pattern_list(self) -> None:
        self.assertIn("version", self.data)
        self.assertIsInstance(self.data.get("patterns"), list)
        self.assertGreater(len(self.data["patterns"]), 0)

    def test_every_pattern_has_required_fields(self) -> None:
        required = {"id", "name", "rule", "evidence"}
        for pattern in self.data["patterns"]:
            self.assertTrue(required.issubset(pattern.keys()), pattern)
            for field in required:
                self.assertTrue(
                    isinstance(pattern[field], str) and pattern[field].strip(),
                    f"{field} must be a non-empty string: {pattern}",
                )

    def test_pattern_ids_are_unique(self) -> None:
        ids = [p["id"] for p in self.data["patterns"]]
        self.assertEqual(len(ids), len(set(ids)), ids)

    def test_pattern_ids_follow_the_ap_prefix(self) -> None:
        for pattern in self.data["patterns"]:
            self.assertRegex(pattern["id"], r"^AP\d+$")

    def test_at_least_one_pattern_is_observed_not_only_seeded(self) -> None:
        """ADR-0017's implementation notes: this list is seeded from a
        reviewed conversation, but is expected to grow from real trials the
        way presets do — gk-todo's no-styling failure is the first such
        entry, tagged distinctly from the seed entries."""
        observed = [p for p in self.data["patterns"] if p["evidence"].startswith("observed:")]
        self.assertGreaterEqual(len(observed), 1)


    def test_evidence_names_a_source_kind(self) -> None:
        """Evidence is the field that separates this list from an opinion.

        Every row says where the pattern came from, and the prefix says how
        strong that is: `seed:` a reviewed conversation, `observed:` a
        gatekit trial whose own screenshot showed it, `reported:` a failure
        seen in another project's review and described to this one rather
        than reproduced here. Keeping `reported:` distinct from `observed:`
        is the point — a pattern this repo has never rendered for itself
        must not claim it did. A row with no prefix is an assertion nobody
        can audit, which is what the evidence field exists to prevent.
        """
        for pattern in self.data["patterns"]:
            self.assertRegex(
                pattern["evidence"],
                r"^(seed|observed|reported):\S",
                f"evidence must be seed:/observed:/reported: {pattern}",
            )

    def test_observed_evidence_carries_a_date(self) -> None:
        """An observation without a date cannot be traced back to the run
        that produced it, and this list grows by citing runs. The same holds
        for a `reported:` row: the review it came from has a date."""
        for pattern in self.data["patterns"]:
            if pattern["evidence"].startswith(("observed:", "reported:")):
                self.assertRegex(
                    pattern["evidence"],
                    r"\d{4}-\d{2}-\d{2}$",
                    f"observed evidence must end in a date: {pattern}",
                )

    def test_rules_are_specific_enough_to_check(self) -> None:
        """A rule is read by an evaluator judging one screenshot. "Looks
        generic" is not checkable; a sentence naming what is on the screen
        is. Length is a crude proxy, but it catches a one-word placeholder.
        """
        for pattern in self.data["patterns"]:
            self.assertGreater(
                len(pattern["rule"]), 40,
                f"rule is too vague to judge a screenshot against: {pattern}",
            )


if __name__ == "__main__":
    unittest.main()
