"""Tests for gatekit.verdict — the 4-state vocabulary and aggregation."""
from __future__ import annotations

import os
import sys
import unittest

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import verdict


class TestVocabulary(unittest.TestCase):
    def test_tokens_are_lowercase_english(self) -> None:
        self.assertEqual(verdict.OK, "ok")
        self.assertEqual(verdict.WARN, "warn")
        self.assertEqual(verdict.FAIL, "fail")
        self.assertEqual(verdict.UNVERIFIED, "unverified")

    def test_order_is_severity_descending(self) -> None:
        self.assertEqual(
            verdict.ORDER,
            [verdict.FAIL, verdict.UNVERIFIED, verdict.WARN, verdict.OK],
        )


class TestAggregate(unittest.TestCase):
    def test_empty_is_unverified_not_ok(self) -> None:
        self.assertEqual(verdict.aggregate([]), verdict.UNVERIFIED)

    def test_all_ok(self) -> None:
        self.assertEqual(verdict.aggregate(["ok", "ok"]), "ok")

    def test_any_fail_wins(self) -> None:
        self.assertEqual(verdict.aggregate(["ok", "warn", "unverified", "fail"]), "fail")

    def test_unverified_beats_warn_and_ok(self) -> None:
        self.assertEqual(verdict.aggregate(["ok", "warn", "unverified"]), "unverified")

    def test_warn_beats_ok(self) -> None:
        self.assertEqual(verdict.aggregate(["ok", "warn"]), "warn")

    def test_unverified_is_never_rounded_to_ok(self) -> None:
        self.assertNotEqual(verdict.aggregate(["ok", "unverified"]), "ok")

    def test_unverified_is_never_rounded_to_fail(self) -> None:
        self.assertNotEqual(verdict.aggregate(["ok", "unverified"]), "fail")

    def test_accepts_any_iterable(self) -> None:
        self.assertEqual(verdict.aggregate(v for v in ["ok", "fail"]), "fail")

    def test_unknown_token_is_unverified(self) -> None:
        self.assertEqual(verdict.aggregate(["ok", "banana"]), "unverified")

    def test_none_token_is_unverified(self) -> None:
        self.assertEqual(verdict.aggregate(["ok", None]), "unverified")

    def test_dict_results_are_accepted(self) -> None:
        results = [{"id": "a", "verdict": "ok"}, {"id": "b", "verdict": "fail"}]
        self.assertEqual(verdict.aggregate(results), "fail")


class TestRender(unittest.TestCase):
    def test_english_labels(self) -> None:
        self.assertEqual(verdict.render("ok", "en"), "OK")
        self.assertEqual(verdict.render("warn", "en"), "WARN")
        self.assertEqual(verdict.render("fail", "en"), "FAIL")
        self.assertEqual(verdict.render("unverified", "en"), "UNVERIFIED")

    def test_korean_labels_are_distinct_and_non_empty(self) -> None:
        labels = {v: verdict.render(v, "ko") for v in verdict.ORDER}
        self.assertEqual(len(set(labels.values())), 4)
        for text in labels.values():
            self.assertTrue(text.strip())

    def test_korean_unverified_is_not_a_pass_or_fail_word(self) -> None:
        ko = verdict.render("unverified", "ko")
        self.assertNotEqual(ko, verdict.render("ok", "ko"))
        self.assertNotEqual(ko, verdict.render("fail", "ko"))

    def test_unknown_lang_falls_back_to_english(self) -> None:
        self.assertEqual(verdict.render("ok", "fr"), "OK")

    def test_unknown_verdict_renders_unverified_label(self) -> None:
        self.assertEqual(verdict.render("banana", "en"), "UNVERIFIED")

    def test_is_valid(self) -> None:
        self.assertTrue(verdict.is_valid("ok"))
        self.assertFalse(verdict.is_valid("banana"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
