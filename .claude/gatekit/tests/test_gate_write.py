"""Tests for gates/write.py — spec before code, and the approval record no tool may write."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import approval  # noqa: E402
from gatekit.gates import write as write_gate  # noqa: E402
from tests import isolation  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "write.py"


def run_gate_subprocess(event: dict, env_extra: "dict | None" = None, *,
                        cwd: pathlib.Path) -> "tuple[int, str, str]":
    """Invoke the gate exactly as Claude Code would: a script fed JSON on stdin, standing
    in the project folder (*cwd*, the test's own project; see tests/isolation.py)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
    env.pop("PYTHONPATH", None)
    # The reason is Korean. The registered hook goes through bin/gatekit.py, which
    # makes stdout UTF-8; the script run on its own takes the encoding from here.
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(env_extra or {})
    proc = isolation.run_gate(
        [sys.executable, str(GATE_SCRIPT)],
        cwd=cwd,
        input=json.dumps(event),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def decision(stdout: str) -> "str | None":
    if not stdout.strip():
        return None
    return json.loads(stdout)["hookSpecificOutput"]["permissionDecision"]


class WriteGateProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        self.gate_md = self.root / "spec" / "05-gate.md"
        self.gate_md.write_text("# Gate\n", encoding="utf-8")

    def tearDown(self) -> None:
        for key in list(os.environ):
            if key.startswith("GATEKIT_"):
                del os.environ[key]
        self._tmp.cleanup()

    def event(self, path: str, tool: str = "Write", **extra) -> dict:
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        payload = {
            "session_id": "sess-write",
            "hook_event_name": "PreToolUse",
            "cwd": str(self.root),
            "tool_name": tool,
            "tool_input": {key: path},
        }
        payload.update(extra)
        return payload


class TestSpecBeforeCode(WriteGateProject):
    """(a) enforce_spec_before_code: code is locked until 05-gate.md is approved."""

    def test_denies_source_write_without_approval(self) -> None:
        result = write_gate.handle(self.event(str(self.root / "src" / "app.ts")))
        self.assertIsNotNone(result)
        self.assertEqual(
            result["hookSpecificOutput"]["permissionDecision"], "deny"
        )

    def test_allows_after_gate_is_approved(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "src" / "app.ts"))))

    def test_stale_approval_denies_again(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        self.gate_md.write_text("# Gate\nchanged\n", encoding="utf-8")
        self.assertIsNotNone(write_gate.handle(self.event(str(self.root / "src" / "app.ts"))))

    def test_allowlist_spec_dir_always_writable(self) -> None:
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "spec" / "01-prd.md"))))

    def test_allowlist_gatekit_dir(self) -> None:
        self.assertIsNone(
            write_gate.handle(self.event(str(self.root / ".gatekit" / "config.json")))
        )

    def test_allowlist_docs_dir(self) -> None:
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "docs" / "adr.md"))))

    def test_allowlist_readme_at_root(self) -> None:
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "README.md"))))

    def test_allowlist_root_markdown(self) -> None:
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "CHANGELOG.md"))))

    def test_nested_markdown_is_not_allowlisted(self) -> None:
        # only *.md at the ROOT is allowlisted, not markdown anywhere
        self.assertIsNotNone(write_gate.handle(self.event(str(self.root / "src" / "notes.md"))))

    # -- case: one file, one verdict (ADR-0022) --------------------------
    def test_allowlist_ignores_case(self) -> None:
        for rel in ("SPEC/01-prd.md", "Spec/new/x.md", "DOCS/adr.md", ".GATEKIT/config.json",
                    "readme.MD", "ReadMe.txt", "CHANGELOG.MD"):
            with self.subTest(rel=rel):
                self.assertIsNone(write_gate.handle(self.event(str(self.root / rel))))
                self.assertIsNone(write_gate.handle(self.event(rel)))

    def test_case_does_not_widen_the_allowlist(self) -> None:
        # what is denied in lower case is denied in every other spelling
        (self.root / "src").mkdir()
        for rel in ("SRC/app.ts", "Src/NOTES.MD", "src/README.md", "SPECS/x.md", "spec2/x.md",
                    "DOCSX/a.md", ".GATEKIT2/x", "X/SPEC/a.md", "lib/DOCS/a.md", "notes.MDX"):
            with self.subTest(rel=rel):
                self.assertIsNotNone(write_gate.handle(self.event(str(self.root / rel))))

    def test_in_allowlist_and_matches_fold_both_sides(self) -> None:
        self.assertTrue(write_gate.in_allowlist("SPEC/x.md"))
        self.assertTrue(write_gate.in_allowlist(".GateKit/runs/a.json"))
        self.assertFalse(write_gate.in_allowlist("SRC/SPEC/x.md"))
        self.assertTrue(write_gate.matches("SRC/Auth/Token.ts", "src/auth/**"))
        self.assertTrue(write_gate.matches("src/auth/token.ts", "SRC/AUTH/*.TS"))
        self.assertTrue(write_gate.matches("SRC/AUTH", "src/auth/**"))
        self.assertFalse(write_gate.matches("SRC/Auth/deep/x.ts", "src/auth/*.ts"))
        self.assertFalse(write_gate.matches("SRC/Billing/x.ts", "src/auth/**"))

    def test_no_spec_dir_means_no_enforcement(self) -> None:
        import shutil

        shutil.rmtree(self.root / "spec")
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "src" / "app.ts"))))

    def test_disabled_by_config(self) -> None:
        (self.root / ".gatekit" / "config.json").write_text(
            json.dumps({"enforce_spec_before_code": False}), encoding="utf-8"
        )
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "src" / "app.ts"))))

    def test_reason_is_korean_by_default(self) -> None:
        """No prompt was seen and no ledger exists: the denial is Korean and names the path."""
        result = write_gate.handle(self.event(str(self.root / "src" / "app.ts")))
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("승인 전에는 코드를 쓸 수 없습니다", reason)
        self.assertIn("차단된 경로: src/app.ts", reason)
        self.assertNotIn("writing code is blocked", reason)

    def test_an_english_prompt_still_gets_a_korean_denial(self) -> None:
        """The user writes only English: the ledger says ko and the gate denies in Korean."""
        from gatekit import ledger
        from gatekit.gates import prompt as prompt_gate

        prompt_gate.handle({
            "session_id": "sess-write", "hook_event_name": "UserPromptSubmit",
            "cwd": str(self.root),
            "prompt": "Please build the login screen and write the source files now.",
        })
        stored = json.loads(
            (self.root / ".gatekit" / "runs" / "sess-write.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["output_lang"], "ko")
        self.assertEqual(ledger.Ledger.load(self.root, "sess-write").output_lang, "ko")

        result = write_gate.handle(self.event(str(self.root / "src" / "app.ts")))
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("승인 전에는 코드를 쓸 수 없습니다", reason)
        self.assertIn("차단된 경로: src/app.ts", reason)
        self.assertNotIn("writing code is blocked", reason)

    def test_edit_tool_uses_file_path(self) -> None:
        self.assertIsNotNone(
            write_gate.handle(self.event(str(self.root / "src" / "a.ts"), tool="Edit"))
        )

    def test_notebook_tool_uses_notebook_path(self) -> None:
        self.assertIsNotNone(
            write_gate.handle(
                self.event(str(self.root / "src" / "a.ipynb"), tool="NotebookEdit")
            )
        )

    def test_relative_path_is_resolved_against_root(self) -> None:
        self.assertIsNotNone(write_gate.handle(self.event("src/app.ts")))

    def test_missing_path_allows(self) -> None:
        event = self.event("x")
        event["tool_input"] = {}
        self.assertIsNone(write_gate.handle(event))

    def test_path_outside_the_project_is_locked_like_code(self) -> None:
        outside = pathlib.Path(os.path.realpath(tempfile.gettempdir())) / "escape.ts"
        self.assertIsNotNone(write_gate.handle(self.event(str(outside))))
        approval.approve(self.root, "spec/05-gate.md")
        self.assertIsNone(write_gate.handle(self.event(str(outside))))

    def test_root_spelled_in_another_case_is_still_the_root(self) -> None:
        # Read as outside the project, the spec file would be denied like code.
        shouted = str(self.root).upper()
        self.assertIsNone(write_gate.handle(self.event(shouted + "\\SPEC\\01-prd.md")))


class TestApprovalRecord(WriteGateProject):
    """``.gatekit/approvals.json`` is written by the ``gatekit.py approve`` process
    alone. A write tool aimed at it is denied, before approval and after it."""

    def reason_of_denial(self, path: str, tool: str = "Write") -> str:
        result = write_gate.handle(self.event(path, tool=tool))
        self.assertIsNotNone(result, "%s %s was allowed" % (tool, path))
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        return result["hookSpecificOutput"]["permissionDecisionReason"]

    def assert_record_denied(self, path: str, tool: str = "Write") -> None:
        self.assertIn("승인 기록", self.reason_of_denial(path, tool), "%s %s" % (tool, path))

    def test_the_record_is_the_file_approve_writes(self) -> None:
        self.assertEqual(write_gate.APPROVAL_RECORD, ".gatekit/approvals.json")
        self.assertFalse((self.root / write_gate.APPROVAL_RECORD).exists())
        approval.approve(self.root, "spec/05-gate.md")
        self.assertTrue((self.root / write_gate.APPROVAL_RECORD).is_file())
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "ok")

    def test_write_and_edit_are_denied_before_approval(self) -> None:
        for tool in ("Write", "Edit", "MultiEdit"):
            with self.subTest(tool=tool):
                self.assert_record_denied(str(self.root / ".gatekit" / "approvals.json"), tool)
                self.assert_record_denied(".gatekit/approvals.json", tool)

    def test_write_and_edit_are_denied_after_approval(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        for tool in ("Write", "Edit", "MultiEdit"):
            with self.subTest(tool=tool):
                self.assert_record_denied(str(self.root / ".gatekit" / "approvals.json"), tool)
                self.assert_record_denied(".gatekit/approvals.json", tool)
        # the approval itself stands, and code is open as before
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "ok")
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "src" / "app.ts"))))

    def test_denied_when_the_approval_went_stale(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        self.gate_md.write_text("# Gate\nchanged\n", encoding="utf-8")
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "fail")
        self.assert_record_denied(".gatekit/approvals.json")
        self.assert_record_denied(".gatekit/approvals.json", "Edit")

    def test_every_spelling_of_the_record_is_denied(self) -> None:
        spellings = (".GATEKIT/Approvals.JSON", ".gatekit\\approvals.json", "./.gatekit/approvals.json",
                     "spec/../.gatekit/approvals.json", ".gatekit/runs/../approvals.json",
                     str(self.root).upper() + "\\.GATEKIT\\APPROVALS.JSON",
                     # Windows opens the same file for each of these (measured)
                     ".gatekit/approvals.json.", ".gatekit/approvals.json ",
                     ".gatekit/approvals.json::$DATA", ".gatekit./approvals.json")
        for rel in spellings:
            with self.subTest(rel=rel, approved=False):
                self.assert_record_denied(rel)
        approval.approve(self.root, "spec/05-gate.md")  # now the file exists as well
        for rel in spellings:
            with self.subTest(rel=rel, approved=True):
                self.assert_record_denied(rel)

    def test_the_reason_says_where_to_go(self) -> None:
        reason = self.reason_of_denial(str(self.root / ".gatekit" / "approvals.json"))
        self.assertIn("승인은 사용자가 정하고", reason)
        self.assertIn("/gatekit-gate", reason)
        self.assertIn("approve 명령", reason)
        self.assertIn("직접 고치지 말고", reason)
        self.assertIn("차단된 경로: .gatekit/approvals.json", reason)
        self.assertNotRegex(reason, r"ADR-\d")
        self.assertNotIn("approval record", reason)  # Korean, not the English table

    def test_the_reason_exists_in_both_languages(self) -> None:
        for lang, phrase in (("ko", "승인 기록"), ("en", "approval record")):
            result = write_gate.decide_path(self.root, ".gatekit/approvals.json", lang)
            reason = result["hookSpecificOutput"]["permissionDecisionReason"]
            self.assertIn(phrase, reason)
            self.assertIn("/gatekit-gate", reason)
            self.assertIn("approve", reason)
            self.assertIn(".gatekit/approvals.json", reason)
            self.assertNotRegex(reason, r"ADR-\d")

    def test_a_forged_record_cannot_open_the_code_lock(self) -> None:
        """The way that was open: write the hash of 05-gate.md into the record."""
        code = str(self.root / "src" / "app.ts")
        self.assertIsNotNone(write_gate.handle(self.event(code)))
        self.assert_record_denied(str(self.root / ".gatekit" / "approvals.json"))
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "unverified")
        self.assertIsNotNone(write_gate.handle(self.event(code)))

    def test_other_files_under_gatekit_are_judged_as_before(self) -> None:
        neighbours = (".gatekit/config.json", ".gatekit/contract.json", ".gatekit/runs/s.json",
                      ".gatekit/approvals.json.bak", ".gatekit/approvals.jsonl",
                      ".gatekit/old/approvals.json", ".gatekit/jobs/j/approvals.json")
        for rel in neighbours:
            with self.subTest(rel=rel, approved=False):
                self.assertIsNone(write_gate.handle(self.event(str(self.root / rel))))
                self.assertIsNone(write_gate.handle(self.event(rel, tool="Edit")))
        # the same name elsewhere is not the record: it is code, locked until approval
        elsewhere = ("approvals.json", "src/.gatekit/approvals.json", "src/approvals.json")
        for rel in elsewhere:
            with self.subTest(rel=rel, approved=False):
                self.assertIn("승인 전에는 코드를 쓸 수 없습니다", self.reason_of_denial(rel))
        approval.approve(self.root, "spec/05-gate.md")
        for rel in neighbours + elsewhere:
            with self.subTest(rel=rel, approved=True):
                self.assertIsNone(write_gate.handle(self.event(str(self.root / rel))))

    def test_no_spec_dir_means_the_gate_stays_back(self) -> None:
        import shutil

        shutil.rmtree(self.root / "spec")
        for tool in ("Write", "Edit"):
            self.assertIsNone(write_gate.handle(
                self.event(str(self.root / ".gatekit" / "approvals.json"), tool=tool)))

    def test_the_rule_does_not_make_the_shell_gates_read_approved_projects(self) -> None:
        self.assertTrue(write_gate.restrictions_active(self.root))
        approval.approve(self.root, "spec/05-gate.md")
        self.assertFalse(write_gate.restrictions_active(self.root))


class TestBracketsAreLetters(unittest.TestCase):
    """A scope names folders as they are on disk. Next.js and its kin use
    ``[id]``, ``[...slug]`` and ``[[...slug]]`` as folder names."""

    def test_a_bracket_folder_matches_itself_and_nothing_else(self) -> None:
        pattern = "src/app/[id]/page.tsx"
        self.assertTrue(write_gate.matches("src/app/[id]/page.tsx", pattern))
        self.assertTrue(write_gate.matches("SRC/App/[ID]/page.tsx", pattern))
        for other in ("src/app/i/page.tsx", "src/app/d/page.tsx", "src/app/id/page.tsx"):
            self.assertFalse(write_gate.matches(other, pattern), other)

    def test_brackets_combine_with_stars(self) -> None:
        self.assertTrue(write_gate.matches("src/app/[id]/edit/page.tsx", "src/app/[id]/**"))
        self.assertTrue(write_gate.matches("src/app/blog/[...slug]/page.tsx", "src/app/**/[...slug]/*.tsx"))
        self.assertTrue(write_gate.matches("src/app/[[...slug]]/page.tsx", "src/app/[[...slug]]/page.tsx"))
        self.assertFalse(write_gate.matches("src/app/x/edit/page.tsx", "src/app/[id]/**"))


class TestNameAfterDoubleStar(unittest.TestCase):
    """``matches`` with something after ``**`` (``src/**/x.ts``): the ``**`` segment stands
    for any number of folders, none included, and what follows it still has to match."""

    def yes(self, relpath: str, pattern: str) -> None:
        self.assertTrue(write_gate.matches(relpath, pattern), "%r should match %r" % (relpath, pattern))

    def no(self, relpath: str, pattern: str) -> None:
        self.assertFalse(write_gate.matches(relpath, pattern), "%r must not match %r" % (relpath, pattern))

    def test_the_named_file_matches_at_every_depth(self) -> None:
        self.yes("src/x.ts", "src/**/x.ts")  # "**" stands for no folder at all
        self.yes("src/a/x.ts", "src/**/x.ts")
        self.yes("src/a/b/c/x.ts", "src/**/x.ts")

    def test_another_name_or_another_place_does_not_match(self) -> None:
        for relpath in ("src/a/y.ts", "src/a/x.tsx", "src/a/ax.ts", "src/a/x.ts/inner.ts",
                        "x.ts", "src", "src/a", "lib/a/x.ts", "srcx/a/x.ts", "a/src/x.ts"):
            with self.subTest(relpath=relpath):
                self.no(relpath, "src/**/x.ts")

    def test_case_is_ignored_on_both_sides(self) -> None:
        self.yes("SRC/A/X.TS", "src/**/x.ts")
        self.yes("src/a/x.ts", "SRC/**/X.TS")
        self.yes("Src/Deep/Er/X.Ts", "sRC/**/x.tS")
        self.no("SRC/A/Y.TS", "src/**/x.ts")
        self.no("LIB/A/X.TS", "src/**/x.ts")

    def test_double_star_first(self) -> None:
        self.yes("x.ts", "**/x.ts")
        self.yes("a/b/x.ts", "**/x.ts")
        self.no("a/b/y.ts", "**/x.ts")
        self.no("a/x.ts/b", "**/x.ts")

    def test_a_wildcard_name_after_double_star_stays_in_one_segment(self) -> None:
        self.yes("src/b.test.ts", "src/**/*.test.ts")
        self.yes("src/a/deep/b.test.ts", "src/**/*.test.ts")
        self.no("src/a/b.ts", "src/**/*.test.ts")
        self.no("src/a/b.test.ts/c.ts", "src/**/*.test.ts")

    def test_a_folder_after_double_star(self) -> None:
        self.yes("src/a/test/b/c.ts", "src/**/test/**")
        self.yes("src/test/a.ts", "src/**/test/**")
        self.yes("src/a/test", "src/**/test/**")  # a trailing "**" also takes no part
        self.no("src/a/tests/c.ts", "src/**/test/**")
        self.no("lib/test/a.ts", "src/**/test/**")

    def test_double_star_gives_parts_back_to_what_follows(self) -> None:
        # the first "a" has to be taken by "**" so that the second one matches the pattern's "a"
        self.yes("src/a/a/x.ts", "src/**/a/x.ts")
        self.yes("src/a/x.ts", "src/**/a/x.ts")
        self.no("src/b/x.ts", "src/**/a/x.ts")
        self.no("src/a/b/x.ts", "src/**/a/x.ts")
        self.yes("src/a/b/x.ts", "src/**/a/**/x.ts")

    def test_two_double_stars_in_a_row(self) -> None:
        self.yes("src/x.ts", "src/**/**/x.ts")
        self.yes("src/a/b/x.ts", "src/**/**/x.ts")
        self.no("src/a/b/y.ts", "src/**/**/x.ts")

    def test_the_pattern_may_be_written_with_a_dot_prefix_or_backslashes(self) -> None:
        self.yes("src/a/x.ts", "./src/**/x.ts")
        self.yes("src/a/x.ts", "src\\**\\x.ts")
        self.no("src/a/y.ts", "src\\**\\x.ts")


class TestSubprocessInvocation(WriteGateProject):
    """The gate must run as a standalone script with no PYTHONPATH help."""

    def test_allow_prints_nothing_and_exits_zero(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        code, out, err = run_gate_subprocess(self.event(str(self.root / "src" / "app.ts")), cwd=self.root)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")

    def test_deny_prints_payload_and_exits_zero(self) -> None:
        code, out, err = run_gate_subprocess(self.event(str(self.root / "src" / "app.ts")), cwd=self.root)
        self.assertEqual(code, 0, err)
        self.assertEqual(decision(out), "deny")
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("승인 전에는 코드를 쓸 수 없습니다", reason)
        self.assertIn("src/app.ts", reason)

    def test_forged_approval_record_is_denied_via_subprocess(self) -> None:
        """The event that opened the code lock without the user: a Write of the
        approval record carrying the hash of 05-gate.md, before any approval."""
        forged = json.dumps({"version": 1, "approvals": [{
            "target": "spec/05-gate.md", "sha256": approval.sha256_file(self.gate_md),
            "approved_by": "user", "approved_at": "2026-10-02T10:00:00+00:00", "note": ""}]})
        record = self.root / ".gatekit" / "approvals.json"
        for tool, tool_input in (
            ("Write", {"file_path": str(record), "content": forged}),
            ("Edit", {"file_path": str(record), "old_string": "[]", "new_string": forged}),
        ):
            with self.subTest(tool=tool):
                event = self.event(str(record), tool=tool)
                event["tool_input"] = tool_input
                code, out, err = run_gate_subprocess(event, cwd=self.root)
                self.assertEqual(code, 0, err)
                self.assertEqual(decision(out), "deny")
                reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("승인 기록", reason)
                self.assertIn("/gatekit-gate", reason)
        self.assertFalse(record.exists())

    def test_internal_error_exits_zero_and_logs(self) -> None:
        """A corrupt ledger must not break the session: allow, exit 0, log."""
        runs = self.root / ".gatekit" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        # A directory where the ledger file belongs makes every ledger op raise.
        (runs / "sess-write.json").mkdir()
        code, out, err = run_gate_subprocess(self.event(str(self.root / "src" / "app.ts")), cwd=self.root)
        self.assertEqual(code, 0, err)
        # It must not crash; either it allowed or denied, but never a traceback.
        self.assertNotIn("Traceback", err)

    def test_empty_stdin_exits_zero(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
        proc = isolation.run_gate(
            [sys.executable, str(GATE_SCRIPT)],
            cwd=self.root,
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_malformed_stdin_exits_zero(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
        proc = isolation.run_gate(
            [sys.executable, str(GATE_SCRIPT)],
            cwd=self.root,
            input="{not json",
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
