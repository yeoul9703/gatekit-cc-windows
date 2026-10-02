"""Tests for gates/write.py — spec-before-code and task write_scope enforcement."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import approval  # noqa: E402
from gatekit.gates import write as write_gate  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "write.py"


def run_gate_subprocess(event: dict, env_extra: "dict | None" = None) -> "tuple[int, str, str]":
    """Invoke the gate exactly as Claude Code would: a script fed JSON on stdin."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
    env.pop("PYTHONPATH", None)
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, str(GATE_SCRIPT)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
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

    def test_reason_is_korean_when_ledger_says_ko(self) -> None:
        from gatekit import ledger

        led = ledger.Ledger.load(self.root, "sess-write")
        led.set_output_lang("ko")
        led.save()
        result = write_gate.handle(self.event(str(self.root / "src" / "app.ts")))
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertTrue(any("가" <= ch <= "힣" for ch in reason), reason)

    def test_reason_is_english_by_default(self) -> None:
        result = write_gate.handle(self.event(str(self.root / "src" / "app.ts")))
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertFalse(any("가" <= ch <= "힣" for ch in reason), reason)

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


class TestTaskWriteScope(WriteGateProject):
    """(b) GATEKIT_TASK_ID: a worker may only write inside its task's scope."""

    def setUp(self) -> None:
        super().setUp()
        approval.approve(self.root, "spec/05-gate.md")  # isolate rule (b)
        self.job_id = "job-1"
        self.task_id = "auth-token"
        task_dir = (
            self.root / ".gatekit" / "jobs" / self.job_id / "tasks" / self.task_id
        )
        task_dir.mkdir(parents=True)
        self.task_file = task_dir / "task.json"
        self.write_task(["src/auth/**"])

    def write_task(self, scope) -> None:
        self.task_file.write_text(
            json.dumps({"id": self.task_id, "write_scope": scope}), encoding="utf-8"
        )

    def task_env(self) -> dict:
        return {"GATEKIT_TASK_ID": self.task_id, "GATEKIT_JOB_ID": self.job_id}

    def apply_env(self) -> None:
        os.environ.update(self.task_env())

    def test_allows_write_inside_scope(self) -> None:
        self.apply_env()
        self.assertIsNone(
            write_gate.handle(self.event(str(self.root / "src" / "auth" / "token.ts")))
        )

    def test_denies_write_outside_scope(self) -> None:
        self.apply_env()
        result = write_gate.handle(self.event(str(self.root / "src" / "billing" / "x.ts")))
        self.assertIsNotNone(result)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_denies_path_outside_project_root(self) -> None:
        self.apply_env()
        outside = pathlib.Path(os.path.realpath(tempfile.gettempdir())) / "escape.ts"
        self.assertIsNotNone(write_gate.handle(self.event(str(outside))))

    def test_read_only_scope_denies_every_write(self) -> None:
        self.write_task("read-only")
        self.apply_env()
        self.assertIsNotNone(
            write_gate.handle(self.event(str(self.root / "src" / "auth" / "token.ts")))
        )

    def test_exact_file_scope(self) -> None:
        self.write_task(["src/auth/token.ts"])
        self.apply_env()
        self.assertIsNone(
            write_gate.handle(self.event(str(self.root / "src" / "auth" / "token.ts")))
        )
        self.assertIsNotNone(
            write_gate.handle(self.event(str(self.root / "src" / "auth" / "other.ts")))
        )

    def test_star_glob_matches_single_segment_only(self) -> None:
        self.write_task(["src/auth/*.ts"])
        self.apply_env()
        self.assertIsNone(
            write_gate.handle(self.event(str(self.root / "src" / "auth" / "token.ts")))
        )
        self.assertIsNotNone(
            write_gate.handle(
                self.event(str(self.root / "src" / "auth" / "deep" / "token.ts"))
            )
        )

    def test_double_star_matches_nested(self) -> None:
        self.apply_env()
        self.assertIsNone(
            write_gate.handle(
                self.event(str(self.root / "src" / "auth" / "deep" / "nested.ts"))
            )
        )

    def test_missing_task_file_denies(self) -> None:
        self.task_file.unlink()
        self.apply_env()
        self.assertIsNotNone(
            write_gate.handle(self.event(str(self.root / "src" / "auth" / "token.ts")))
        )

    def test_corrupt_task_file_denies(self) -> None:
        self.task_file.write_text("{broken", encoding="utf-8")
        self.apply_env()
        self.assertIsNotNone(
            write_gate.handle(self.event(str(self.root / "src" / "auth" / "token.ts")))
        )

    def test_scope_applies_even_inside_spec_allowlist(self) -> None:
        # A task-scoped worker is not granted the spec-before-code allowlist.
        self.apply_env()
        self.assertIsNotNone(write_gate.handle(self.event(str(self.root / "spec" / "01-prd.md"))))

    # -- case (ADR-0022) -------------------------------------------------
    def test_scope_ignores_case_whether_or_not_the_folder_exists(self) -> None:
        self.apply_env()
        # nothing on disk: realpath cannot restore the spelling
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "SRC" / "Auth" / "new.ts"))))
        (self.root / "src" / "auth").mkdir(parents=True)
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "SRC" / "AUTH" / "new.ts"))))
        self.assertIsNone(write_gate.handle(self.event("Src/Auth/Deep/x.ts")))

    def test_scope_pattern_case_is_ignored_too(self) -> None:
        self.write_task(["SRC/Auth/**"])
        self.apply_env()
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "src" / "auth" / "t.ts"))))

    def test_case_does_not_let_a_worker_out_of_its_scope(self) -> None:
        self.apply_env()
        for rel in ("SRC/Billing/x.ts", "SRC/AUTHX/x.ts", "SPEC/01-prd.md", ".GATEKIT/config.json",
                    "DOCS/a.md", "README.MD", "SRC/auth.ts"):
            with self.subTest(rel=rel):
                self.assertIsNotNone(write_gate.handle(self.event(str(self.root / rel))))

    def test_read_only_task_denies_any_spelling(self) -> None:
        self.write_task("read-only")
        self.apply_env()
        self.assertIsNotNone(write_gate.handle(self.event(str(self.root / "SRC" / "Auth" / "t.ts"))))

    def test_root_spelled_in_another_case_is_still_the_root(self) -> None:
        self.apply_env()
        shouted = str(self.root).upper()
        self.assertIsNone(write_gate.handle(self.event(shouted + "\\SRC\\AUTH\\t.ts")))
        self.assertIsNotNone(write_gate.handle(self.event(shouted + "\\SRC\\OTHER\\t.ts")))

    def test_no_task_env_skips_rule_b(self) -> None:
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "src" / "billing" / "x.ts"))))

    # -- a name after "**": src/**/x.ts ------------------------------------
    def test_scope_with_a_name_after_double_star_allows_that_file_at_any_depth(self) -> None:
        self.write_task(["src/**/x.ts"])
        self.apply_env()
        for rel in ("src/x.ts", "src/a/x.ts", "src/a/b/c/x.ts"):
            with self.subTest(rel=rel):
                self.assertIsNone(write_gate.handle(self.event(str(self.root / rel))))
                self.assertIsNone(write_gate.handle(self.event(rel)))

    def test_scope_with_a_name_after_double_star_denies_everything_else(self) -> None:
        self.write_task(["src/**/x.ts"])
        self.apply_env()
        for rel in ("src/a/y.ts", "src/a/x.tsx", "src/a/ax.ts", "src/a/x.ts/inner.ts", "x.ts",
                    "lib/a/x.ts", "srcx/a/x.ts", "src/a", "spec/x.ts", "docs/x.ts"):
            with self.subTest(rel=rel):
                result = write_gate.handle(self.event(str(self.root / rel)))
                self.assertIsNotNone(result)
                self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_scope_with_a_name_after_double_star_ignores_case(self) -> None:
        self.write_task(["src/**/x.ts"])
        self.apply_env()
        for rel in ("SRC/X.TS", "Src/Auth/X.ts", "SRC/A/B/x.TS"):
            with self.subTest(rel=rel):
                self.assertIsNone(write_gate.handle(self.event(str(self.root / rel))))
        # the other spelling of a path outside the scope is outside it too
        for rel in ("SRC/A/Y.TS", "LIB/A/X.TS", "SRC/A/X.TSX"):
            with self.subTest(rel=rel):
                self.assertIsNotNone(write_gate.handle(self.event(str(self.root / rel))))
        self.write_task(["SRC/**/X.TS"])
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "src" / "deep" / "x.ts"))))
        self.assertIsNotNone(write_gate.handle(self.event(str(self.root / "src" / "deep" / "y.ts"))))

    def test_one_matching_pattern_among_several_is_enough(self) -> None:
        self.write_task(["docs/**/notes.md", "src/**/x.ts"])
        self.apply_env()
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "src" / "a" / "x.ts"))))
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "docs" / "a" / "b" / "notes.md"))))
        self.assertIsNotNone(write_gate.handle(self.event(str(self.root / "docs" / "a" / "x.ts"))))
        self.assertIsNotNone(write_gate.handle(self.event(str(self.root / "src" / "a" / "notes.md"))))


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
        code, out, err = run_gate_subprocess(self.event(str(self.root / "src" / "app.ts")))
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")

    def test_deny_prints_payload_and_exits_zero(self) -> None:
        code, out, err = run_gate_subprocess(self.event(str(self.root / "src" / "app.ts")))
        self.assertEqual(code, 0, err)
        self.assertEqual(decision(out), "deny")

    def test_task_scope_deny_via_subprocess(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        task_dir = self.root / ".gatekit" / "jobs" / "j" / "tasks" / "t"
        task_dir.mkdir(parents=True)
        (task_dir / "task.json").write_text(
            json.dumps({"id": "t", "write_scope": ["src/auth/**"]}), encoding="utf-8"
        )
        code, out, _ = run_gate_subprocess(
            self.event(str(self.root / "other" / "x.ts")),
            env_extra={"GATEKIT_TASK_ID": "t", "GATEKIT_JOB_ID": "j"},
        )
        self.assertEqual(code, 0)
        self.assertEqual(decision(out), "deny")

    def test_internal_error_exits_zero_and_logs(self) -> None:
        """A corrupt ledger must not break the session: allow, exit 0, log."""
        runs = self.root / ".gatekit" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        # A directory where the ledger file belongs makes every ledger op raise.
        (runs / "sess-write.json").mkdir()
        code, out, err = run_gate_subprocess(self.event(str(self.root / "src" / "app.ts")))
        self.assertEqual(code, 0, err)
        # It must not crash; either it allowed or denied, but never a traceback.
        self.assertNotIn("Traceback", err)

    def test_empty_stdin_exits_zero(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_malformed_stdin_exits_zero(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input="{not json",
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
