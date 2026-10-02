"""Tests for spec/00-discovery.md validation — the discovery gates are code, not prose."""
from __future__ import annotations

import json
import os
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

KO_HEADINGS = "## 불편 목록\n\n## 고른 문제\n\n## 기한\n\n## 심화 게이트\n\n## 남은 것\n"
EN_HEADINGS = "## Pain list\n\n## Chosen problem\n\n## Deadline\n\n## Deepening gates\n\n## Open items\n"


def full_record() -> dict:
    return {
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


def discovery_text(record: dict, lang: str = "en") -> str:
    head = KO_HEADINGS if lang == "ko" else EN_HEADINGS
    return "# discovery\n\n" + head + "\n```gatekit-discovery\n" + json.dumps(record, ensure_ascii=False) + "\n```\n"


def findings_for(report: dict, name: str = "00-discovery.md") -> list:
    return [f for f in report["findings"] if f["file"] == name]


class DiscoveryProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-en", self.root)
        self.path = self.root / "spec" / "00-discovery.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, record: dict, lang: str = "en") -> dict:
        self.path.write_text(discovery_text(record, lang), encoding="utf-8")
        return spec.validate(self.root, lang)


class TestAbsence(DiscoveryProject):
    def test_absent_discovery_is_silent(self) -> None:
        """Discovery is optional: a set without it must not even warn."""
        report = spec.validate(self.root)
        self.assertEqual(findings_for(report), [])
        self.assertEqual(report["verdict"], "ok")


class TestFullRecord(DiscoveryProject):
    def test_complete_record_has_no_findings(self) -> None:
        report = self.write(full_record())
        self.assertEqual(findings_for(report), [])

    def test_korean_headings_validate_in_korean(self) -> None:
        report = self.write(full_record(), lang="ko")
        self.assertEqual([f for f in findings_for(report) if f["verdict"] == "fail"], [])

    def test_missing_heading_fails(self) -> None:
        self.path.write_text(
            "# d\n\n## Pain list\n\n```gatekit-discovery\n" + json.dumps(full_record()) + "\n```\n",
            encoding="utf-8",
        )
        report = spec.validate(self.root, "en")
        self.assertIn("fail", [f["verdict"] for f in findings_for(report)])


class TestFence(DiscoveryProject):
    def test_missing_fence_fails(self) -> None:
        self.path.write_text("# d\n\n" + EN_HEADINGS, encoding="utf-8")
        report = spec.validate(self.root, "en")
        verdicts = [f["verdict"] for f in findings_for(report)]
        self.assertIn("fail", verdicts)

    def test_two_fences_fail(self) -> None:
        text = discovery_text(full_record()) + "\n```gatekit-discovery\n{}\n```\n"
        self.path.write_text(text, encoding="utf-8")
        report = spec.validate(self.root, "en")
        self.assertIn("fail", [f["verdict"] for f in findings_for(report)])

    def test_empty_problem_fails(self) -> None:
        record = full_record()
        record["problem"] = "  "
        report = self.write(record)
        self.assertIn("fail", [f["verdict"] for f in findings_for(report)])


class TestGates(DiscoveryProject):
    """Each unfilled deepening gate is a warn, never silent and never a fail:
    the record is honest about what it lacks, and interview reads it as such."""

    def assert_one_warn_naming(self, report: dict, token: str) -> None:
        warns = [f for f in findings_for(report) if f["verdict"] == "warn"]
        self.assertEqual(len(warns), 1, json.dumps(findings_for(report), indent=1))
        self.assertIn(token, warns[0]["message"])

    def test_plural_or_empty_user_warns(self) -> None:
        record = full_record()
        record["user"] = ""
        self.assert_one_warn_naming(self.write(record), "user")

    def test_short_current_way_warns(self) -> None:
        record = full_record()
        record["current_way"] = ["do it manually"]
        self.assert_one_warn_naming(self.write(record), "current_way")

    def test_non_numeric_frequency_warns(self) -> None:
        record = full_record()
        record["frequency_per_month"] = "often"
        self.assert_one_warn_naming(self.write(record), "frequency_per_month")

    def test_missing_minutes_warns(self) -> None:
        record = full_record()
        del record["minutes_per_run"]
        self.assert_one_warn_naming(self.write(record), "minutes_per_run")

    def test_short_why_chain_warns(self) -> None:
        record = full_record()
        record["why_chain"] = ["symptom", "why1", "why2"]
        self.assert_one_warn_naming(self.write(record), "why_chain")

    def test_repeated_why_does_not_count(self) -> None:
        record = full_record()
        record["why_chain"] = ["symptom", "not organised", "not organised", "not organised", "cause"]
        self.assert_one_warn_naming(self.write(record), "why_chain")

    def test_paraphrased_whys_do_not_count(self) -> None:
        record = full_record()
        record["why_chain"] = [
            "files hard to find",
            "hard to find files",
            "the files are hard to find",
            "finding the files is hard",
            "cause",
        ]
        self.assert_one_warn_naming(self.write(record), "why_chain")

    def test_non_string_whys_do_not_count(self) -> None:
        record = full_record()
        record["why_chain"] = ["symptom", None, {}, [], 3]
        self.assert_one_warn_naming(self.write(record), "why_chain")

    def test_unpassed_not_a_list_fails(self) -> None:
        record = full_record()
        record["unpassed"] = "why_chain"
        self.assertIn("fail", [f["verdict"] for f in findings_for(self.write(record))])

    def test_unpassed_naming_a_filled_gate_warns(self) -> None:
        record = full_record()
        record["unpassed"] = ["user"]
        self.assert_one_warn_naming(self.write(record), "user")

    def test_not_applicable_in_list_form_passes(self) -> None:
        record = full_record()
        record["failed_attempts"] = ["Not-Applicable"]
        self.assertEqual(findings_for(self.write(record)), [])

    def test_non_dict_fence_reports_once(self) -> None:
        self.path.write_text("# d\n\n" + EN_HEADINGS + "\n```gatekit-discovery\n[1, 2]\n```\n", encoding="utf-8")
        report = spec.validate(self.root, "en")
        fails = [f for f in findings_for(report) if f["verdict"] == "fail"]
        self.assertEqual(len(fails), 1)

    def test_no_failed_attempts_warns(self) -> None:
        record = full_record()
        record["failed_attempts"] = []
        self.assert_one_warn_naming(self.write(record), "failed_attempts")

    def test_not_applicable_attempts_pass(self) -> None:
        record = full_record()
        record["failed_attempts"] = "not-applicable"
        self.assertEqual(findings_for(self.write(record)), [])

    def test_bad_attempt_result_warns(self) -> None:
        record = full_record()
        record["failed_attempts"] = [{"tried": "x", "result": "meh", "why": "y"}]
        self.assert_one_warn_naming(self.write(record), "failed_attempts")

    def test_missing_deadline_warns(self) -> None:
        record = full_record()
        record["deadline"] = ""
        self.assert_one_warn_naming(self.write(record), "deadline")

    def test_declared_unpassed_gate_still_warns_but_says_declared(self) -> None:
        record = full_record()
        record["why_chain"] = []
        record["unpassed"] = ["why_chain"]
        report = self.write(record)
        warns = [f for f in findings_for(report) if f["verdict"] == "warn"]
        self.assertEqual(len(warns), 1)
        self.assertIn("unpassed", warns[0]["message"])

    def test_unknown_unpassed_name_fails(self) -> None:
        record = full_record()
        record["unpassed"] = ["vibes"]
        self.assertIn("fail", [f["verdict"] for f in findings_for(self.write(record))])

    def test_messages_localised(self) -> None:
        record = full_record()
        record["user"] = ""
        report = self.write(record, lang="ko")
        warns = [f for f in findings_for(report) if f["verdict"] == "warn"]
        self.assertTrue(any("실사용자" in w["message"] for w in warns))


class TestTemplates(unittest.TestCase):
    def test_discovery_templates_exist_and_fence_parses(self) -> None:
        for lang in ("ko", "en"):
            path = PLUGIN_DIR.parent / "skills" / "gatekit-discover" / "assets" / lang / "00-discovery.md"
            self.assertTrue(path.exists(), path)
            detailed = spec._parse_fences_detailed(path.read_text(encoding="utf-8"), "gatekit-discovery")
            self.assertEqual(len(detailed), 1)
            self.assertIsNone(detailed[0][2])

    def test_gate_names_constant(self) -> None:
        self.assertEqual(
            spec.DISCOVERY_GATES,
            ("user", "current_way", "frequency_per_month", "minutes_per_run", "why_chain", "failed_attempts"),
        )


if __name__ == "__main__":
    unittest.main()
