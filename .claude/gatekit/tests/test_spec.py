"""Tests for gatekit.spec.

The kernel modules `paths` and `verdict` are owned by another agent and
may not exist yet. When one is missing this module installs a minimal stub in
`sys.modules` before importing `gatekit.spec`, so these tests are meaningful on
their own. When the real module is present it is used unchanged, and these
tests then also exercise the real integration.
"""
from __future__ import annotations

import importlib
import io
import json
import os
import pathlib
import sys
import types
import unittest
from contextlib import redirect_stdout

PLUGIN_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "spec"
SKILLS_DIR = PLUGIN_DIR.parent / "skills"

#: Which skill owns each spec template (its ``assets/<file>``).
TEMPLATE_OWNER = {
    "00-discovery.md": "discover",
    "01-prd.md": "interview",
    "02-screens.md": "mockup",
    "02-design.md": "design",
    "03-architecture.md": "interview",
    "04-tasks.md": "tasks",
    "05-gate.md": "gate",
    "PROGRESS.md": "build",
    "RECOVERY.md": "build",
}


def template_path(name: str) -> pathlib.Path:
    return SKILLS_DIR / ("gatekit-" + TEMPLATE_OWNER[name]) / "assets" / name


# ---------------------------------------------------------------------------
# stubs for kernel modules that may not exist yet
# ---------------------------------------------------------------------------


def _ensure(module_name: str, build):
    """Import `module_name`; on failure install the stub `build()` produces."""
    try:
        importlib.import_module(module_name)
    except ImportError:
        sys.modules[module_name] = build()


def _stub_paths() -> types.ModuleType:
    mod = types.ModuleType("gatekit.paths")

    def project_root(cwd=None):
        return pathlib.Path(cwd or os.getcwd())

    mod.project_root = project_root
    mod.state_dir = lambda root: pathlib.Path(root) / ".gatekit"
    mod.spec_dir = lambda root: pathlib.Path(root) / "spec"
    mod.gatekit_root = lambda: PLUGIN_DIR
    mod.skills_root = lambda: SKILLS_DIR
    mod.skill_dir = lambda name: SKILLS_DIR / ("gatekit-" + name)
    return mod


def _stub_verdict() -> types.ModuleType:
    mod = types.ModuleType("gatekit.verdict")
    mod.OK, mod.WARN, mod.FAIL, mod.UNVERIFIED = "ok", "warn", "fail", "unverified"
    mod.ORDER = ["ok", "warn", "unverified", "fail"]

    def aggregate(verdicts):
        verdicts = list(verdicts)
        if "fail" in verdicts:
            return "fail"
        if "unverified" in verdicts:
            return "unverified"
        if "warn" in verdicts:
            return "warn"
        return "ok"

    mod.aggregate = aggregate
    mod.render = lambda v, lang: v
    return mod


_ensure("gatekit.paths", _stub_paths)
_ensure("gatekit.verdict", _stub_verdict)

from gatekit import spec  # noqa: E402


def messages(report, file=None):
    return [
        f["message"]
        for f in report["findings"]
        if file is None or f["file"] == file
    ]


def verdicts_for(report, file):
    return [f["verdict"] for f in report["findings"] if f["file"] == file]


# ---------------------------------------------------------------------------
# fence parsing
# ---------------------------------------------------------------------------


class ParseFencesTests(unittest.TestCase):
    def test_parses_every_named_fence(self):
        text = (
            "intro\n"
            "```gatekit-task\n{\"id\": \"a\"}\n```\n"
            "middle\n"
            "```gatekit-task\n{\"id\": \"b\"}\n```\n"
        )
        self.assertEqual(
            [t["id"] for t in spec.parse_fences(text, "gatekit-task")], ["a", "b"]
        )

    def test_ignores_other_fence_names(self):
        text = "```python\n{\"id\": \"a\"}\n```\n"
        self.assertEqual(spec.parse_fences(text, "gatekit-task"), [])

    def test_skips_malformed_bodies(self):
        text = "```gatekit-task\n{oops}\n```\n```gatekit-task\n{\"id\": \"b\"}\n```\n"
        self.assertEqual(
            [t["id"] for t in spec.parse_fences(text, "gatekit-task")], ["b"]
        )

    def test_rejects_non_object_body(self):
        text = "```gatekit-task\n[1, 2]\n```\n"
        self.assertEqual(spec.parse_fences(text, "gatekit-task"), [])

    def test_reports_line_number_of_malformed_fence(self):
        text = "line one\nline two\n```gatekit-task\n{oops}\n```\n"
        detailed = spec._parse_fences_detailed(text, "gatekit-task")
        self.assertEqual(len(detailed), 1)
        line_no, parsed, err = detailed[0]
        self.assertEqual(line_no, 3)
        self.assertIsNone(parsed)
        self.assertIsNotNone(err)


# ---------------------------------------------------------------------------
# valid sets
# ---------------------------------------------------------------------------


class ValidSetTests(unittest.TestCase):
    def test_korean_set_has_no_failures(self):
        report = spec.validate(FIXTURES / "valid-ko")
        self.assertEqual(report["lang"], "ko")
        self.assertNotIn(
            "fail",
            [f["verdict"] for f in report["findings"]],
            msg=json.dumps(report["findings"], ensure_ascii=False, indent=2),
        )
        self.assertEqual(report["verdict"], "ok")

    def test_lang_is_korean_when_not_given_whatever_the_prd_holds(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-ko", root)
            prd = root / "spec" / "01-prd.md"
            prd.write_text(
                prd.read_text(encoding="utf-8") + "\n" + "An English paragraph. " * 200,
                encoding="utf-8",
            )
            report = spec.validate(root)
            self.assertEqual(report["lang"], "ko")
            self.assertEqual(report["verdict"], "ok")
            # a language with no message table falls back to Korean too
            self.assertEqual(spec.validate(root, lang="fr")["lang"], "ko")

    def test_english_headings_are_not_a_second_valid_set(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-ko", root)
            path = root / "spec" / "02-screens.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace("## 근거 없는 영역", "## Negative space"),
                encoding="utf-8",
            )
            report = spec.validate(root)
            self.assertEqual(report["verdict"], "fail")
            # one finding: the Korean heading is missing. The English one is
            # an extra heading like any other, not a finding of its own.
            self.assertEqual(
                messages(report, "02-screens.md"),
                [spec._msg("ko", "heading_missing", heading="## 근거 없는 영역")],
            )


# ---------------------------------------------------------------------------
# missing files
# ---------------------------------------------------------------------------


class MissingFileTests(unittest.TestCase):
    def test_missing_required_files_fail(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "spec").mkdir()
            report = spec.validate(root)
            self.assertEqual(report["verdict"], "fail")
            self.assertEqual(verdicts_for(report, "01-prd.md"), ["fail"])
            self.assertEqual(verdicts_for(report, "05-gate.md"), ["fail"])
            # optional files only warn
            self.assertEqual(verdicts_for(report, "PROGRESS.md"), ["warn"])
            self.assertEqual(verdicts_for(report, "RECOVERY.md"), ["warn"])

    def test_missing_optional_file_only_warns(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-ko", root)
            (root / "spec" / "PROGRESS.md").unlink()
            report = spec.validate(root)
            self.assertEqual(report["verdict"], "warn")
            self.assertEqual(verdicts_for(report, "PROGRESS.md"), ["warn"])


# ---------------------------------------------------------------------------
# headings
# ---------------------------------------------------------------------------


class HeadingTests(unittest.TestCase):
    def test_missing_heading_is_a_failure(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-ko", root)
            path = root / "spec" / "03-architecture.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace("## 제약", "## 한계"),
                encoding="utf-8",
            )
            report = spec.validate(root)
            self.assertEqual(report["verdict"], "fail")
            self.assertTrue(
                any("## 제약" in m for m in messages(report, "03-architecture.md"))
            )

    def test_extra_non_canonical_heading_is_allowed(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-ko", root)
            path = root / "spec" / "03-architecture.md"
            # an extra heading is not a finding, in Korean or in English
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\n## 열린 질문\n\n없음.\n\n## Open questions\n\nNone.\n",
                encoding="utf-8",
            )
            self.assertEqual(spec.validate(root)["verdict"], "ok")


# ---------------------------------------------------------------------------
# assumption ledger
# ---------------------------------------------------------------------------


class LedgerTests(unittest.TestCase):
    def test_inline_without_row_fails_and_row_without_inline_warns(self):
        report = spec.validate(FIXTURES / "ledger-mismatch")
        self.assertEqual(report["verdict"], "fail")
        prd = [f for f in report["findings"] if f["file"] == "01-prd.md"]
        fails = [f["message"] for f in prd if f["verdict"] == "fail"]
        warns = [f["message"] for f in prd if f["verdict"] == "warn"]
        self.assertTrue(any("2" in m for m in fails), fails)
        self.assertTrue(any("3" in m for m in warns), warns)

    def test_matched_ledger_produces_no_finding(self):
        report = spec.validate(FIXTURES / "valid-ko")
        self.assertEqual([f for f in report["findings"] if f["file"] == "01-prd.md"], [])

    def test_english_inline_marker_is_recognised(self):
        text = "> ⚠️ Assumption 4: the API is stable.\n"
        self.assertEqual(spec._inline_assumption_numbers(text), [4])

    def test_korean_inline_marker_is_recognised(self):
        text = "> ⚠️ 가정 7: 사용자는 로그인 상태다.\n"
        self.assertEqual(spec._inline_assumption_numbers(text), [7])

    def test_trailing_number_form_is_recognised(self):
        text = "> ⚠️ Assumption: the API is stable (A2)\n"
        self.assertEqual(spec._inline_assumption_numbers(text), [2])


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------


class TaskTests(unittest.TestCase):
    def _validate_tasks(self, body: str, lang: str = "en"):
        return spec._check_tasks(body, lang)

    def test_same_round_scope_collision_fails(self):
        report = spec.validate(FIXTURES / "scope-collision")
        self.assertEqual(report["verdict"], "fail")
        msgs = messages(report, "04-tasks.md")
        self.assertTrue(
            any("note-store" in m and "note-ui" in m for m in msgs), msgs
        )

    def test_different_rounds_may_overlap(self):
        body = (
            "## Task list\n"
            '```gatekit-task\n{"id": "a", "write_scope": ["src/x/**"], '
            '"gates": [{"name": "t", "argv": ["true"]}], "round": 1}\n```\n'
            '```gatekit-task\n{"id": "b", "write_scope": ["src/x/y.ts"], '
            '"gates": [{"name": "t", "argv": ["true"]}], "round": 2}\n```\n'
        )
        self.assertEqual(self._validate_tasks(body), [])

    def test_duplicate_ids_fail(self):
        body = (
            '```gatekit-task\n{"id": "a", "write_scope": ["src/x/**"], '
            '"gates": [{"name": "t", "argv": ["true"]}], "round": 1}\n```\n'
            '```gatekit-task\n{"id": "a", "write_scope": ["src/y/**"], '
            '"gates": [{"name": "t", "argv": ["true"]}], "round": 1}\n```\n'
        )
        msgs = [f["message"] for f in self._validate_tasks(body)]
        self.assertTrue(any("Duplicate task id" in m for m in msgs), msgs)

    def test_empty_write_scope_fails_but_read_only_passes(self):
        empty = (
            '```gatekit-task\n{"id": "a", "write_scope": [], '
            '"gates": [{"name": "t", "argv": ["true"]}], "round": 1}\n```\n'
        )
        msgs = [f["message"] for f in self._validate_tasks(empty)]
        self.assertTrue(any("write_scope" in m for m in msgs), msgs)

        read_only = (
            '```gatekit-task\n{"id": "a", "write_scope": "read-only", '
            '"gates": [{"name": "t", "argv": ["true"]}], "round": 1}\n```\n'
        )
        self.assertEqual(self._validate_tasks(read_only), [])

    def test_unresolvable_dependency_fails(self):
        body = (
            '```gatekit-task\n{"id": "a", "write_scope": ["src/x/**"], '
            '"gates": [{"name": "t", "argv": ["true"]}], '
            '"depends_on": ["ghost"], "round": 1}\n```\n'
        )
        msgs = [f["message"] for f in self._validate_tasks(body)]
        self.assertTrue(any("ghost" in m for m in msgs), msgs)

    def test_task_without_gate_fails(self):
        body = (
            '```gatekit-task\n{"id": "a", "write_scope": ["src/x/**"], '
            '"gates": [], "round": 1}\n```\n'
        )
        msgs = [f["message"] for f in self._validate_tasks(body)]
        self.assertTrue(any("gate" in m.lower() for m in msgs), msgs)

    def _task_with_read(self, read) -> str:
        task = {"id": "a", "write_scope": ["src/x/**"],
                "gates": [{"name": "t", "argv": ["true"]}], "round": 1, "read": read}
        return "```gatekit-task\n%s\n```\n" % json.dumps(task)

    def test_read_is_optional_and_takes_relative_paths(self):
        # a listed file need not exist: an earlier task may be the one that writes it
        for read in ([], ["spec/01-prd.md", "src/store/index.ts", "docs/a..b.md", "src/**"]):
            with self.subTest(read=read):
                self.assertEqual(self._validate_tasks(self._task_with_read(read)), [])

    def test_read_of_the_wrong_shape_fails(self):
        for read in (
            "spec/01-prd.md",            # not a list
            ["C:/dev/app/src/a.ts"],     # an absolute path
            ["/etc/hosts"],              # an absolute path
            ["../other/README.md"],      # leaves the project
            ["src/../../x.md"],          # leaves the project
            ["@spec/01-prd.md"],         # `@` reaches a subagent as text, not as the file
            ["src\\a.ts"],               # a backslash
            ["spec/01-prd.md", ""],      # an empty string
            ["spec/01-prd.md", 3],       # not a string
        ):
            with self.subTest(read=read):
                findings = self._validate_tasks(self._task_with_read(read))
                self.assertEqual([f["verdict"] for f in findings], ["fail"], findings)
                self.assertIn("Task a has an invalid read", findings[0]["message"])
        # the message shows the entry that is wrong, in both languages
        bad = self._task_with_read(["spec/01-prd.md", "@src/a.ts"])
        self.assertIn("@src/a.ts", self._validate_tasks(bad)[0]["message"])
        korean = self._validate_tasks(bad, "ko")[0]["message"]
        self.assertIn("작업 a의 read가 잘못되었습니다: @src/a.ts", korean)

    def test_malformed_fence_reports_line_number(self):
        report = spec.validate(FIXTURES / "malformed-fence")
        self.assertEqual(report["verdict"], "fail")
        msgs = messages(report, "04-tasks.md")
        malformed = [m for m in msgs if "gatekit-task" in m]
        self.assertTrue(malformed, msgs)
        self.assertTrue(
            any(any(ch.isdigit() for ch in m) for m in malformed),
            msg="no line number in %r" % malformed,
        )

    def test_glob_intersection_rules(self):
        self.assertTrue(spec._globs_intersect("src/a/**", "src/a/b.ts"))
        self.assertTrue(spec._globs_intersect("src/a/b.ts", "src/a/**"))
        self.assertTrue(spec._globs_intersect("src/a/*.ts", "src/a/b.ts"))
        self.assertTrue(spec._globs_intersect("src/a/**", "src/a/**"))
        self.assertFalse(spec._globs_intersect("src/a/**", "src/b/**"))
        self.assertFalse(spec._globs_intersect("src/a/b.ts", "src/a/c.ts"))
        self.assertFalse(spec._globs_intersect("src/ab/**", "src/a/c.ts"))


# ---------------------------------------------------------------------------
# criteria
# ---------------------------------------------------------------------------


class CriterionTests(unittest.TestCase):
    def test_missing_not_counted_section_fails(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-ko", root)
            path = root / "spec" / "05-gate.md"
            text = path.read_text(encoding="utf-8")
            self.assertIn("## 완료로 보지 않는 조건", text)
            path.write_text(
                text.replace("## 완료로 보지 않는 조건", "## 메모"), encoding="utf-8"
            )
            report = spec.validate(root)
            self.assertEqual(report["verdict"], "fail")
            self.assertIn(
                spec._msg("ko", "crit_not_done_section"), messages(report, "05-gate.md")
            )

    def test_empty_argv_fails(self):
        body = (
            "## 완료로 보지 않는 조건\n"
            '```gatekit-criterion\n{"id": "c", "argv": []}\n```\n'
        )
        msgs = [f["message"] for f in spec._check_criteria(body, "en")]
        self.assertTrue(any("argv" in m for m in msgs), msgs)

    def test_non_string_argv_fails(self):
        body = (
            "## 완료로 보지 않는 조건\n"
            '```gatekit-criterion\n{"id": "c", "argv": ["python3", 3]}\n```\n'
        )
        msgs = [f["message"] for f in spec._check_criteria(body, "en")]
        self.assertTrue(any("argv" in m for m in msgs), msgs)

    def test_duplicate_criterion_ids_fail(self):
        body = (
            "## 완료로 보지 않는 조건\n"
            '```gatekit-criterion\n{"id": "c", "argv": ["true"]}\n```\n'
            '```gatekit-criterion\n{"id": "c", "argv": ["true"]}\n```\n'
        )
        msgs = [f["message"] for f in spec._check_criteria(body, "en")]
        self.assertEqual(msgs, [spec._msg("en", "crit_duplicate_id", id="c")])

    def test_no_criteria_fails(self):
        body = "## 완료로 보지 않는 조건\n\nnothing here\n"
        msgs = [f["message"] for f in spec._check_criteria(body, "en")]
        self.assertTrue(any("gatekit-criterion" in m for m in msgs), msgs)


# ---------------------------------------------------------------------------
# traceability
# ---------------------------------------------------------------------------


class TraceabilityTests(unittest.TestCase):
    def test_unreferenced_task_warns(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-ko", root)
            path = root / "spec" / "05-gate.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace("note-ui-tests", "other-tests"),
                encoding="utf-8",
            )
            report = spec.validate(root)
            self.assertEqual(report["verdict"], "warn")
            warn = [
                f
                for f in report["findings"]
                if f["verdict"] == "warn" and "note-ui" in f["message"]
            ]
            self.assertTrue(warn, report["findings"])

    def test_referenced_tasks_produce_no_warning(self):
        report = spec.validate(FIXTURES / "valid-ko")
        self.assertEqual(
            [f for f in report["findings"] if "note-store" in f["message"]], []
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class CliTests(unittest.TestCase):
    def test_valid_set_exits_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = spec.run(["validate", "--root", str(FIXTURES / "valid-ko")])
        self.assertEqual(code, 0)
        # Human-readable output is localized; the label comes from
        # verdict.render, so assert only that something was rendered.
        self.assertTrue(buf.getvalue().startswith("spec: "), buf.getvalue())
        self.assertNotIn("[fail]", buf.getvalue())

    def test_failing_set_exits_one(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = spec.run(["validate", "--root", str(FIXTURES / "ledger-mismatch")])
        self.assertEqual(code, 1)
        self.assertIn("[fail]", buf.getvalue())

    def test_warn_only_set_exits_zero(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-ko", root)
            (root / "spec" / "PROGRESS.md").unlink()
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = spec.run(["validate", "--root", str(root)])
            self.assertEqual(code, 0)

    def test_json_output_is_parseable(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            spec.run(["validate", "--json", "--root", str(FIXTURES / "valid-ko")])
        report = json.loads(buf.getvalue())
        self.assertEqual(report["verdict"], "ok")
        self.assertEqual(report["lang"], "ko")
        self.assertIsInstance(report["findings"], list)

    def test_unknown_subcommand_returns_two(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(spec.run([]), 2)


# ---------------------------------------------------------------------------
# heading map and templates agree
# ---------------------------------------------------------------------------


class TemplateConsistencyTests(unittest.TestCase):
    def test_the_heading_map_holds_one_korean_set(self):
        hm = spec.heading_map()
        self.assertNotIn("ko", hm)
        self.assertNotIn("en", hm)
        self.assertEqual(sorted(hm["headings"]), sorted(hm["files"]))
        for name in hm["files"]:
            headings = spec.canonical_headings(name)
            self.assertTrue(headings, name)
            for heading in headings:
                self.assertRegex(heading, r"^## [가-힣]", "%s: %r" % (name, heading))
                self.assertNotRegex(heading, r"[A-Za-z]", "%s: %r" % (name, heading))

    def test_every_template_carries_its_canonical_headings(self):
        for name in spec.spec_files():
            path = template_path(name)
            self.assertTrue(path.exists(), "missing template %s" % name)
            present = set(spec._present_headings(path.read_text(encoding="utf-8")))
            for heading in spec.canonical_headings(name):
                self.assertIn(heading, present, "%s lacks %r" % (name, heading))

    def test_template_fences_are_valid_json(self):
        checks = [
            ("04-tasks.md", "gatekit-task"),
            ("05-gate.md", "gatekit-criterion"),
        ]
        for name, fence in checks:
            text = template_path(name).read_text(encoding="utf-8")
            detailed = spec._parse_fences_detailed(text, fence)
            self.assertTrue(detailed, "%s has no %s fence" % (name, fence))
            for line_no, _, err in detailed:
                self.assertIsNone(err, "%s line %d: %s" % (name, line_no, err))

    def test_templates_stay_under_120_lines(self):
        for name in spec.spec_files():
            path = template_path(name)
            count = len(path.read_text(encoding="utf-8").splitlines())
            self.assertLessEqual(count, 120, "%s is %d lines" % (name, count))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class ExpectFieldTests(unittest.TestCase):
    """spec validate rejects an `expect` the contract would refuse to derive."""

    def setUp(self):
        import shutil, tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-ko", self.root)
        self.gate = self.root / "spec" / "05-gate.md"

    def tearDown(self):
        self._tmp.cleanup()

    def with_expect(self, expect) -> list:
        text = self.gate.read_text(encoding="utf-8")
        import re
        new = re.sub(
            r'"expect":\s*\{[^}]*\}', '"expect": ' + json.dumps(expect), text, count=1
        )
        self.gate.write_text(new, encoding="utf-8")
        return [f for f in spec.validate(self.root, "en")["findings"] if f["file"] == "05-gate.md" and f["verdict"] == "fail"]

    def test_valid_output_expectation_passes(self):
        self.assertEqual(self.with_expect({"exit": 0, "stdout_not_contains": ["skipped"]}), [])

    def test_unknown_key_fails(self):
        fails = self.with_expect({"exit": 0, "stdout_contain": "x"})
        self.assertTrue(any("stdout_contain" in f["message"] for f in fails))

    def test_wrong_type_fails(self):
        self.assertTrue(self.with_expect({"stdout_contains": {"a": 1}}))

    def test_bad_regex_fails(self):
        self.assertTrue(self.with_expect({"stdout_regex": "["}))


# ---------------------------------------------------------------------------
# 02-design.md (ADR-0008 decision 2)
# ---------------------------------------------------------------------------


class DesignFileTests(unittest.TestCase):
    """02-design.md is an optional stage with its own canonical H2 set."""

    def test_design_file_is_listed_and_optional(self):
        hm = spec.heading_map()
        self.assertIn("02-design.md", hm["files"])
        self.assertIn("02-design.md", hm["absent_ok"])
        self.assertNotIn("02-design.md", hm["required_files"])

    def test_canonical_headings(self):
        self.assertEqual(
            spec.canonical_headings("02-design.md"),
            ["## 출처", "## 디자인 패턴", "## 컴포넌트", "## 디자인 토큰", "## 근거 없는 영역"],
        )

    def test_absent_design_file_produces_no_finding(self):
        report = spec.validate(FIXTURES / "valid-ko")
        self.assertEqual(
            [f for f in report["findings"] if f["file"] == "02-design.md"], []
        )

    def test_a_design_file_with_every_canonical_heading_has_no_finding(self):
        ko = "\n".join(
            ["# 디자인", "## 출처", "## 디자인 패턴", "## 컴포넌트", "## 디자인 토큰", "## 근거 없는 영역", ""]
        )
        self.assertEqual(spec._check_headings("02-design.md", ko, "ko"), [])

    def test_a_heading_shared_with_02_screens_is_canonical_in_both_files(self):
        """`## 컴포넌트` is canonical in both 02-screens.md and 02-design.md;
        _check_headings works per file."""
        self.assertIn("## 컴포넌트", spec.canonical_headings("02-screens.md"))
        self.assertIn("## 컴포넌트", spec.canonical_headings("02-design.md"))
        screens = "\n".join(spec.canonical_headings("02-screens.md")) + "\n"
        self.assertEqual(spec._check_headings("02-screens.md", screens, "ko"), [])


# ---------------------------------------------------------------------------
# tokens.json (ADR-0008 decision 9)
# ---------------------------------------------------------------------------


class TokensJsonTests(unittest.TestCase):
    def setUp(self):
        import shutil, tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-ko", self.root)
        self.tokens = self.root / "spec" / "tokens.json"

    def tearDown(self):
        self._tmp.cleanup()

    def findings(self):
        return [
            f for f in spec.validate(self.root, "en")["findings"]
            if f["file"] == "tokens.json"
        ]

    def write(self, text):
        self.tokens.write_text(text, encoding="utf-8")

    def write_json(self, data):
        self.write(json.dumps(data, ensure_ascii=False))

    def test_absent_tokens_file_produces_no_finding(self):
        self.assertEqual(self.findings(), [])

    def test_v1_shape_is_accepted(self):
        self.write_json(
            {
                "source": "figma.com/file/abc",
                "color": {"primary": "#000000"},
                "space": {"md": "16px"},
                "font": {"body": "16px/1.5"},
            }
        )
        self.assertEqual(self.findings(), [])

    def test_explicit_version_one_is_accepted(self):
        self.write_json({"version": 1, "source": "x", "color": {"a": "#000"}})
        self.assertEqual(self.findings(), [])

    def test_valid_v2_is_accepted(self):
        self.write_json(
            {
                "version": 2,
                "source": ["spec/design/home.png"],
                "patterns": [
                    {"id": "P1", "rule": "Cards in a list.", "applies_to": ["S1"], "evidence": "spec/design/home.png"}
                ],
                "color": {"primary": {"value": "#000", "evidence": "P1"}},
                "radius": {"sm": "4px"},
            }
        )
        self.assertEqual(self.findings(), [])

    def test_unparsable_file_warns_never_fails(self):
        self.write("{not json")
        found = self.findings()
        self.assertTrue(found)
        self.assertTrue(all(f["verdict"] == "warn" for f in found))

    def test_non_object_file_warns(self):
        self.write("[1, 2]")
        self.assertTrue(all(f["verdict"] == "warn" for f in self.findings()))

    def test_v2_source_must_be_a_list(self):
        self.write_json({"version": 2, "source": "one string", "patterns": []})
        found = self.findings()
        self.assertTrue(any("source" in f["message"] for f in found))
        self.assertTrue(all(f["verdict"] == "warn" for f in found))

    def test_v2_patterns_must_be_a_list(self):
        self.write_json({"version": 2, "source": [], "patterns": {"P1": {}}})
        self.assertTrue(any("patterns" in f["message"] for f in self.findings()))

    def test_pattern_row_missing_a_key_warns_and_names_it(self):
        self.write_json(
            {"version": 2, "source": [], "patterns": [{"id": "P1", "rule": "x", "applies_to": "all"}]}
        )
        found = self.findings()
        self.assertTrue(any("evidence" in f["message"] for f in found))
        self.assertTrue(all(f["verdict"] == "warn" for f in found))

    def test_pattern_applies_to_must_be_all_or_a_list(self):
        self.write_json(
            {
                "version": 2,
                "source": [],
                "patterns": [{"id": "P1", "rule": "x", "applies_to": 3, "evidence": "y"}],
            }
        )
        self.assertTrue(any("applies_to" in f["message"] for f in self.findings()))

    def test_group_must_map_to_an_object(self):
        self.write_json({"version": 2, "source": [], "patterns": [], "color": "#000"})
        found = self.findings()
        self.assertTrue(any("color" in f["message"] for f in found))
        self.assertTrue(all(f["verdict"] == "warn" for f in found))

    def test_token_value_must_be_a_string_or_object(self):
        self.write_json({"version": 2, "source": [], "patterns": [], "color": {"primary": [1]}})
        self.assertTrue(any("primary" in f["message"] for f in self.findings()))

    def test_a_malformed_tokens_file_never_makes_the_set_fail(self):
        self.write("{not json")
        self.assertNotEqual(spec.validate(self.root, "en")["verdict"], "fail")


# ---------------------------------------------------------------------------
# ledger supersession (ADR-0008 decision 8)
# ---------------------------------------------------------------------------


class LedgerSupersessionTests(unittest.TestCase):
    """A row whose evidence says `supersedes A<n>` retires row n."""

    HEAD = "\n".join(
        ["# PRD", "## 문제", "## 현재 상태 (측정값)", "## 목표", "## 목표가 아닌 것",
         "## 사용자", "## 기능", "## 수용 기준", ""]
    )

    def prd(self, inline_nums, rows, lang="en"):
        """The headings are the one Korean set. `lang` picks only the wording
        of the inline marker; both wordings are recognised."""
        marker = "> Assumption %d: text" if lang == "en" else "> 가정 %d: 내용"
        lines = [self.HEAD]
        lines += [marker % n for n in inline_nums]
        lines += ["", "## 가정 원장", "", "| # | Assumption | Impact | Evidence |", "|---|---|---|---|"]
        for num, evidence in rows:
            lines.append("| A%d | something | low | %s |" % (num, evidence))
        return "\n".join(lines) + "\n"

    def findings(self, text, lang="en"):
        return spec._check_ledger(text, lang)

    def test_superseded_row_still_referenced_alone_warns(self):
        text = self.prd([1], [(1, "interview"), (2, "supersedes A1: spec/design/home.png")])
        found = self.findings(text)
        self.assertTrue(any(f["verdict"] == "warn" and "A1" in f["message"] for f in found))

    def test_successor_also_referenced_is_silent(self):
        text = self.prd([1, 2], [(1, "interview"), (2, "supersedes A1: spec/design/home.png")])
        messages = [f["message"] for f in self.findings(text)]
        self.assertFalse(any("supersed" in m.lower() or "대체" in m for m in messages))

    def test_korean_marker_form_is_recognised(self):
        text = self.prd([1], [(1, "인터뷰"), (2, "A1 대체: spec/design/home.png")], lang="ko")
        found = self.findings(text, "ko")
        self.assertTrue(any(f["verdict"] == "warn" and "A1" in f["message"] for f in found))

    def test_orphan_checks_are_unchanged(self):
        text = self.prd([3], [(1, "interview")])
        verdicts = {f["verdict"] for f in self.findings(text)}
        self.assertIn("fail", verdicts)   # inline 3 has no row
        self.assertIn("warn", verdicts)   # row 1 has no inline

    def test_no_supersession_marker_produces_no_supersession_finding(self):
        text = self.prd([1, 2], [(1, "interview"), (2, "interview")])
        self.assertEqual(self.findings(text), [])

    def test_korean_plain_digit_before_대체_is_not_a_supersession(self):
        """`카드 3 대체 수단` is prose about alternatives, not a ledger pointer.

        A bare digit before 대체 was matching, which retired row 3 on the
        strength of an unrelated sentence. A supersession must name the row.
        """
        text = self.prd([1], [(1, "인터뷰"), (4, "카드 3 대체 수단을 지원한다")], lang="ko")
        messages = [f["message"] for f in self.findings(text, "ko")]
        self.assertFalse(any("대체" in m for m in messages), messages)

    def test_korean_option_phrasing_is_not_a_supersession(self):
        text = self.prd([1], [(1, "인터뷰"), (4, "옵션 1 대체 불가")], lang="ko")
        messages = [f["message"] for f in self.findings(text, "ko")]
        self.assertFalse(any("대체" in m for m in messages), messages)

    def test_korean_a_prefixed_row_reference_is_a_supersession(self):
        text = self.prd([1], [(1, "인터뷰"), (2, "A1 대체")], lang="ko")
        found = self.findings(text, "ko")
        self.assertTrue(any(f["verdict"] == "warn" and "A1" in f["message"] for f in found))

    def test_supersessions_records_only_explicit_row_references(self):
        self.assertEqual(spec._supersessions("| A4 | x | low | 카드 3 대체 수단을 지원한다 |"), {})
        self.assertEqual(spec._supersessions("| A4 | x | low | 옵션 1 대체 불가 |"), {})
        self.assertEqual(spec._supersessions("| A4 | x | low | A2 대체 |"), {2: 4})
        self.assertEqual(spec._supersessions("| A4 | x | low | A2 번 대체 |"), {2: 4})
        self.assertEqual(spec._supersessions("| A4 | x | low | 대체: A2 |"), {2: 4})
        self.assertEqual(spec._supersessions("| A4 | x | low | supersedes A2: home.png |"), {2: 4})

    def test_english_supersedes_still_requires_a_row_number(self):
        self.assertEqual(spec._supersessions("| A4 | x | low | supersedes nothing |"), {})


# ------------------------------------- ADR-0011: a preview is never evidence


class TestPreviewNotEvidence(unittest.TestCase):
    """ADR-0011 decision 4: a drawing made from the spec cannot support it."""

    def setUp(self):
        import shutil, tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-ko", self.root)
        self.screens = self.root / "spec" / "02-screens.md"

    def tearDown(self):
        self._tmp.cleanup()

    def findings_for(self, text: str) -> list:
        self.screens.write_text(text, encoding="utf-8")
        report = spec.validate(self.root)
        return [f for f in report["findings"] if "preview" in f["message"].lower()]

    def test_clean_screen_spec_has_no_preview_finding(self):
        self.assertEqual(self.findings_for(self.screens.read_text(encoding="utf-8")), [])

    def test_citing_a_preview_file_fails(self):
        text = self.screens.read_text(encoding="utf-8")
        text += "\n| S9 | Extra | F1 | spec/design/preview-demo.html S9 |\n"
        findings = self.findings_for(text)
        self.assertTrue(findings)
        self.assertEqual(findings[0]["verdict"], "fail")

    def test_the_finding_names_the_file_it_was_found_in(self):
        text = self.screens.read_text(encoding="utf-8")
        text += "\n| S9 | Extra | F1 | spec/design/preview-demo.html S9 |\n"
        self.assertEqual(self.findings_for(text)[0]["file"], "02-screens.md")

    def test_a_bare_preview_filename_is_caught_too(self):
        text = self.screens.read_text(encoding="utf-8")
        text += "\n| S9 | Extra | F1 | preview-tetris.html |\n"
        self.assertTrue(self.findings_for(text))

    def test_prose_mentioning_the_preview_is_not_a_citation(self):
        text = self.screens.read_text(encoding="utf-8")
        text += "\nThe owner looked at spec/design/preview-demo.html before the build.\n"
        self.assertEqual(self.findings_for(text), [])

    def test_an_unrelated_html_path_is_not_a_preview(self):
        text = self.screens.read_text(encoding="utf-8")
        text += "\n| S9 | Extra | F1 | spec/design/apple-preview.html |\n"
        self.assertEqual(self.findings_for(text), [])

    def test_the_check_also_covers_the_design_file(self):
        (self.root / "spec" / "02-design.md").write_text(
            "# Design\n\n| P1 | Rule | all | spec/design/preview-demo.html |\n",
            encoding="utf-8",
        )
        report = spec.validate(self.root)
        hits = [f for f in report["findings"]
                if "preview" in f["message"].lower() and f["file"] == "02-design.md"]
        self.assertTrue(hits)

    def test_an_external_url_is_not_a_preview(self):
        text = self.screens.read_text(encoding="utf-8")
        text += "\n| S9 | Extra | F1 | https://example.com/preview-widget.html |\n"
        self.assertEqual(self.findings_for(text), [])

    def test_a_row_inside_a_fence_is_not_a_citation(self):
        text = self.screens.read_text(encoding="utf-8")
        text += "\n```\n| S9 | Extra | F1 | spec/design/preview-demo.html |\n```\n"
        self.assertEqual(self.findings_for(text), [])

    def test_a_local_preview_path_is_still_caught(self):
        text = self.screens.read_text(encoding="utf-8")
        text += "\n| S9 | Extra | F1 | ./spec/design/preview-demo.html |\n"
        self.assertTrue(self.findings_for(text))


# ------------------- ADR-0013 decision 5: a verification task is not a task


class TestVerificationShapedTask(unittest.TestCase):
    """`e2e-full-flow` on gk-trial2 was task 9 of 9, gated on the whole system.
    It failed five times and passed on the seventh, once everything else
    existed — and the same command was already a criterion in 05-gate.md."""

    def setUp(self):
        import shutil, tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-ko", self.root)
        self.tasks = self.root / "spec" / "04-tasks.md"

    def tearDown(self):
        self._tmp.cleanup()

    def fence(self, **task) -> str:
        return "```gatekit-task\n%s\n```\n" % json.dumps(task)

    def findings_for(self, *tasks) -> list:
        body = "# Tasks\n\n" + "".join(self.fence(**t) for t in tasks)
        self.tasks.write_text(body, encoding="utf-8")
        report = spec.validate(self.root)
        return [f for f in report["findings"]
                if f["file"] == "04-tasks.md" and "05-gate" in f["message"]]

    def base(self, **kw) -> dict:
        task = {"id": "t", "title": "t", "instruction": "do it",
                "write_scope": ["src/**"], "depends_on": [],
                "gates": [{"name": "g", "argv": ["true"]}], "round": 1}
        task.update(kw)
        return task

    def test_test_only_scope_with_two_dependencies_warns(self) -> None:
        found = self.findings_for(
            self.base(id="a"), self.base(id="b"),
            self.base(id="e2e", write_scope=["e2e/**", "tests/seed/**"],
                      depends_on=["a", "b"], round=2))
        self.assertTrue(found)
        self.assertEqual(found[0]["verdict"], "warn")
        self.assertIn("e2e", found[0]["message"])

    def test_one_dependency_does_not_warn(self) -> None:
        self.assertEqual(self.findings_for(
            self.base(id="a"),
            self.base(id="suite", write_scope=["tests/**"], depends_on=["a"], round=2)), [])

    def test_a_source_path_in_scope_never_warns(self) -> None:
        self.assertEqual(self.findings_for(
            self.base(id="a"), self.base(id="b"),
            self.base(id="feat", write_scope=["src/feat.ts", "tests/feat/**"],
                      depends_on=["a", "b"], round=2)), [])

    def test_read_only_scope_does_not_warn(self) -> None:
        self.assertEqual(self.findings_for(
            self.base(id="a"), self.base(id="b"),
            self.base(id="audit", write_scope="read-only",
                      depends_on=["a", "b"], round=2)), [])

    def test_the_warning_is_never_a_fail(self) -> None:
        """The signature is suggestive, not certain — a legitimate test-only
        task exists (adding a missing regression suite), so this must not be
        able to fail a spec on its own."""
        found = self.findings_for(
            self.base(id="a"), self.base(id="b", write_scope=["lib/**"]),
            self.base(id="e2e", write_scope=["e2e/**"], depends_on=["a", "b"], round=2))
        self.assertTrue(found)
        self.assertEqual([f["verdict"] for f in found], ["warn"])

    def test_every_test_directory_shape_counts(self) -> None:
        for scope in (["e2e/**"], ["tests/**"], ["spec/cases/**"],
                      ["src/__tests__/**"], ["playwright.config.ts", "e2e/**"]):
            self.assertTrue(
                self.findings_for(
                    self.base(id="a"), self.base(id="b"),
                    self.base(id="v", write_scope=scope, depends_on=["a", "b"], round=2)),
                msg="expected a warning for %r" % (scope,))

    def test_a_chain_end_is_caught_even_with_one_direct_dependency(self) -> None:
        """The real `e2e-full-flow` declared one dependency and waited on eight.

        Counting direct dependencies missed it entirely; transitive reach is
        what "passes only once several tasks are done" actually means.
        """
        found = self.findings_for(
            self.base(id="a"),
            self.base(id="b", write_scope=["lib/**"], depends_on=["a"], round=2),
            self.base(id="c", write_scope=["ui/**"], depends_on=["b"], round=3),
            self.base(id="e2e", write_scope=["e2e/**"], depends_on=["c"], round=4))
        self.assertTrue(found)
        self.assertIn("3", found[0]["message"])

    def test_a_test_task_behind_a_single_task_still_does_not_warn(self) -> None:
        self.assertEqual(self.findings_for(
            self.base(id="a"),
            self.base(id="suite", write_scope=["tests/**"], depends_on=["a"], round=2)), [])

    def test_a_dependency_cycle_does_not_hang(self) -> None:
        self.findings_for(
            self.base(id="x", write_scope=["e2e/**"], depends_on=["y"]),
            self.base(id="y", write_scope=["lib/**"], depends_on=["x"]))
