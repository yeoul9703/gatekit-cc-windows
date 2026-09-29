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

    def test_no_task_env_skips_rule_b(self) -> None:
        self.assertIsNone(write_gate.handle(self.event(str(self.root / "src" / "billing" / "x.ts"))))


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


class TestApplyPatch(WriteGateProject):
    """Codex edits files through apply_patch; the patch text names the files."""

    PATCH = (
        "*** Begin Patch\n*** Update File: src/auth/token.ts\n@@\n-a\n+b\n"
        "*** Add File: src/auth/new.ts\n+x\n*** Delete File: src/old.ts\n*** End Patch\n"
    )

    def patch_event(self, patch: str) -> dict:
        return {
            "session_id": "sess-write",
            "hook_event_name": "PreToolUse",
            "cwd": str(self.root),
            "tool_name": "apply_patch",
            "tool_input": {"command": patch},
        }

    def test_patch_targets_are_parsed(self) -> None:
        self.assertEqual(
            write_gate.patch_targets(self.PATCH),
            ["src/auth/token.ts", "src/auth/new.ts", "src/old.ts"],
        )

    def test_move_to_counts_as_target(self) -> None:
        text = "*** Begin Patch\n*** Update File: a.ts\n*** Move to: b/c.ts\n*** End Patch\n"
        self.assertEqual(write_gate.patch_targets(text), ["a.ts", "b/c.ts"])

    def test_patch_denied_before_approval(self) -> None:
        result = write_gate.handle(self.patch_event(self.PATCH))
        self.assertIsNotNone(result)
        self.assertIn("src/auth/token.ts", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_patch_to_spec_allowed(self) -> None:
        text = "*** Begin Patch\n*** Update File: spec/01-prd.md\n@@\n-a\n+b\n*** End Patch\n"
        self.assertIsNone(write_gate.handle(self.patch_event(text)))

    def test_patch_allowed_after_approval(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        self.assertIsNone(write_gate.handle(self.patch_event(self.PATCH)))

    def test_patch_with_no_file_lines_denied_when_restricted(self) -> None:
        result = write_gate.handle(self.patch_event("*** Begin Patch\n*** End Patch\n"))
        self.assertIsNotNone(result)
        self.assertIn("cannot determine", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_patch_with_no_file_lines_allowed_when_unrestricted(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        self.assertIsNone(write_gate.handle(self.patch_event("*** Begin Patch\n*** End Patch\n")))

    def test_scoped_worker_patch_outside_scope_denied(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")
        task_dir = self.root / ".gatekit" / "jobs" / "j" / "tasks" / "auth"
        task_dir.mkdir(parents=True)
        (task_dir / "task.json").write_text(json.dumps({"id": "auth", "write_scope": ["src/auth/**"]}))
        os.environ["GATEKIT_TASK_ID"] = "auth"
        os.environ["GATEKIT_JOB_ID"] = "j"
        result = write_gate.handle(self.patch_event(self.PATCH))
        self.assertIsNotNone(result)
        self.assertIn("src/old.ts", result["hookSpecificOutput"]["permissionDecisionReason"])
