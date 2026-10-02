"""Tests for gates/spawn.py — declared write scopes for subagents."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import ledger  # noqa: E402
from gatekit.gates import spawn as spawn_gate  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "spawn.py"


def scope_fence(obj) -> str:
    body = obj if isinstance(obj, str) else json.dumps(obj)
    return "```gatekit-scope\n" + body + "\n```"


class SpawnProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        self.session = "sess-spawn"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def event(self, prompt: str, description: str = "") -> dict:
        tool_input = {"prompt": prompt}
        if description:
            tool_input["description"] = description
        return {
            "session_id": self.session,
            "hook_event_name": "PreToolUse",
            "cwd": str(self.root),
            "tool_name": "Task",
            "tool_input": tool_input,
        }

    def led(self) -> ledger.Ledger:
        return ledger.Ledger.load(self.root, self.session)

    def is_deny(self, result) -> bool:
        return (
            result is not None
            and result["hookSpecificOutput"]["permissionDecision"] == "deny"
        )


class TestAllow(SpawnProject):
    def test_valid_fence_allows_and_records_scope(self) -> None:
        prompt = "Do the auth work.\n" + scope_fence(
            {"write_scope": ["src/auth/**"], "stop_when": "tests pass", "tools": "inherit"}
        )
        self.assertIsNone(spawn_gate.handle(self.event(prompt, description="auth-agent")))
        scopes = self.led().data["scopes"]
        self.assertEqual(len(scopes), 1)
        self.assertEqual(scopes[0]["write_scope"], ["src/auth/**"])
        self.assertEqual(scopes[0]["owner"], "auth-agent")

    def test_owner_falls_back_to_prompt_hash(self) -> None:
        prompt = "work\n" + scope_fence({"write_scope": ["src/a/**"], "stop_when": "x"})
        spawn_gate.handle(self.event(prompt))
        owner = self.led().data["scopes"][0]["owner"]
        expected = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
        self.assertEqual(owner, expected)
        self.assertEqual(len(owner), 12)

    def test_read_only_scope_allowed(self) -> None:
        prompt = "review only\n" + scope_fence(
            {"write_scope": "read-only", "stop_when": "review posted"}
        )
        self.assertIsNone(spawn_gate.handle(self.event(prompt)))
        self.assertEqual(self.led().data["scopes"][0]["write_scope"], "read-only")

    def test_two_read_only_agents_do_not_conflict(self) -> None:
        prompt = "r\n" + scope_fence({"write_scope": "read-only", "stop_when": "x"})
        self.assertIsNone(spawn_gate.handle(self.event(prompt, description="a")))
        self.assertIsNone(spawn_gate.handle(self.event(prompt, description="b")))

    def test_disjoint_scopes_both_allowed(self) -> None:
        first = "a\n" + scope_fence({"write_scope": ["src/auth/**"], "stop_when": "x"})
        second = "b\n" + scope_fence({"write_scope": ["src/billing/**"], "stop_when": "x"})
        self.assertIsNone(spawn_gate.handle(self.event(first, description="a")))
        self.assertIsNone(spawn_gate.handle(self.event(second, description="b")))
        self.assertEqual(len(self.led().data["scopes"]), 2)

    def test_fence_with_surrounding_prose(self) -> None:
        prompt = (
            "# Task\nSome instructions.\n\n"
            + scope_fence({"write_scope": ["src/x/**"], "stop_when": "done"})
            + "\n\nMore prose afterwards.\n"
        )
        self.assertIsNone(spawn_gate.handle(self.event(prompt)))

    def test_event_is_recorded(self) -> None:
        prompt = "a\n" + scope_fence({"write_scope": ["src/a/**"], "stop_when": "x"})
        spawn_gate.handle(self.event(prompt))
        kinds = [e["kind"] for e in self.led().data["events"]]
        self.assertIn("scope_declared", kinds)


class TestDeny(SpawnProject):
    def test_missing_fence_denies(self) -> None:
        self.assertTrue(self.is_deny(spawn_gate.handle(self.event("just do the thing"))))

    def test_empty_prompt_denies(self) -> None:
        self.assertTrue(self.is_deny(spawn_gate.handle(self.event(""))))

    def test_invalid_json_denies(self) -> None:
        self.assertTrue(
            self.is_deny(spawn_gate.handle(self.event("x\n" + scope_fence("{not json"))))
        )

    def test_non_object_json_denies(self) -> None:
        self.assertTrue(
            self.is_deny(spawn_gate.handle(self.event("x\n" + scope_fence("[1,2,3]"))))
        )

    def test_missing_write_scope_key_denies(self) -> None:
        self.assertTrue(
            self.is_deny(spawn_gate.handle(self.event("x\n" + scope_fence({"stop_when": "x"}))))
        )

    def test_missing_stop_when_denies(self) -> None:
        self.assertTrue(
            self.is_deny(
                spawn_gate.handle(self.event("x\n" + scope_fence({"write_scope": ["a/**"]})))
            )
        )

    def test_empty_write_scope_list_denies(self) -> None:
        self.assertTrue(
            self.is_deny(
                spawn_gate.handle(
                    self.event("x\n" + scope_fence({"write_scope": [], "stop_when": "x"}))
                )
            )
        )

    def test_bad_write_scope_type_denies(self) -> None:
        self.assertTrue(
            self.is_deny(
                spawn_gate.handle(
                    self.event("x\n" + scope_fence({"write_scope": 42, "stop_when": "x"}))
                )
            )
        )

    def test_unknown_write_scope_string_denies(self) -> None:
        # only the literal "read-only" is a valid string form
        self.assertTrue(
            self.is_deny(
                spawn_gate.handle(
                    self.event("x\n" + scope_fence({"write_scope": "anything", "stop_when": "x"}))
                )
            )
        )

    def test_conflicting_scope_denies(self) -> None:
        first = "a\n" + scope_fence({"write_scope": ["src/auth/**"], "stop_when": "x"})
        spawn_gate.handle(self.event(first, description="a"))
        second = "b\n" + scope_fence({"write_scope": ["src/auth/token.ts"], "stop_when": "x"})
        result = spawn_gate.handle(self.event(second, description="b"))
        self.assertTrue(self.is_deny(result))
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("a", reason)

    def test_conflict_names_the_release_command_and_a_released_scope_is_free(self) -> None:
        first = "a\n" + scope_fence({"write_scope": ["src/auth/**"], "stop_when": "x"})
        spawn_gate.handle(self.event(first, description="a"))
        second = "b\n" + scope_fence({"write_scope": ["src/auth/token.ts"], "stop_when": "x"})
        reason = spawn_gate.handle(self.event(second, description="b"))[
            "hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("ledger release-scopes --session", reason)
        led = self.led()
        self.assertEqual(led.release_scopes(), 1)  # the first agent has finished
        led.save()
        self.assertIsNone(spawn_gate.handle(self.event(second, description="b")))

    def test_conflict_ignores_case(self) -> None:
        first = "a\n" + scope_fence({"write_scope": ["src/auth/**"], "stop_when": "x"})
        second = "b\n" + scope_fence({"write_scope": ["SRC/Auth/token.ts"], "stop_when": "x"})
        self.assertIsNone(spawn_gate.handle(self.event(first, description="a")))
        self.assertTrue(self.is_deny(spawn_gate.handle(self.event(second, description="b"))))

    def test_conflicting_scope_is_not_recorded(self) -> None:
        first = "a\n" + scope_fence({"write_scope": ["src/auth/**"], "stop_when": "x"})
        spawn_gate.handle(self.event(first, description="a"))
        second = "b\n" + scope_fence({"write_scope": ["src/auth/**"], "stop_when": "x"})
        spawn_gate.handle(self.event(second, description="b"))
        self.assertEqual(len(self.led().data["scopes"]), 1)

    def test_denial_is_recorded_as_event(self) -> None:
        spawn_gate.handle(self.event("no fence here"))
        kinds = [e["kind"] for e in self.led().data["events"]]
        self.assertIn("spawn_denied", kinds)

    def test_no_regex_over_prose(self) -> None:
        """Prose merely mentioning write_scope must not satisfy the gate."""
        prompt = 'Please use write_scope: ["src/**"] and stop_when: "done".'
        self.assertTrue(self.is_deny(spawn_gate.handle(self.event(prompt))))

    def test_reason_is_korean_by_default(self) -> None:
        """No language was ever stored for this session: the denial is Korean."""
        result = spawn_gate.handle(self.event("no fence"))
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("펜스가 없습니다", reason)
        self.assertIn("gatekit-scope", reason)
        self.assertNotIn("this spawn has no", reason)


class TestSubprocess(SpawnProject):
    def _run(self, event: dict) -> "tuple[int, str, str]":
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        # The reason is Korean. The registered hook goes through bin/gatekit.py, which
        # makes stdout UTF-8; the script run on its own takes the encoding from here.
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_allow_via_subprocess(self) -> None:
        prompt = "a\n" + scope_fence({"write_scope": ["src/a/**"], "stop_when": "x"})
        code, out, err = self._run(self.event(prompt))
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")

    def test_deny_via_subprocess(self) -> None:
        code, out, err = self._run(self.event("no fence"))
        self.assertEqual(code, 0, err)
        block = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(block["permissionDecision"], "deny")
        self.assertIn("펜스가 없습니다", block["permissionDecisionReason"])

    def test_internal_error_exits_zero_and_logs(self) -> None:
        runs = self.root / ".gatekit" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / f"{self.session}.json").mkdir()  # unwritable ledger path
        prompt = "a\n" + scope_fence({"write_scope": ["src/a/**"], "stop_when": "x"})
        code, _, err = self._run(self.event(prompt))
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)
        log = runs / "hook-errors.log"
        self.assertTrue(log.is_file())
        self.assertIn("PreToolUse", log.read_text(encoding="utf-8"))

    def test_malformed_stdin_exits_zero(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input="{oops",
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestUnmanagedProject(unittest.TestCase):
    """A project gatekit does not manage is none of the gate's business.

    The plugin installs globally, so this hook fires in every project the
    user opens. Denying a spawn there blocks work gatekit was never asked
    to govern; the scope fence only means something once `.gatekit/` exists.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".git").mkdir()  # a git repo, but not a gatekit project

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def event(self, prompt: str) -> dict:
        return {
            "session_id": "unmanaged", "hook_event_name": "PreToolUse",
            "cwd": str(self.root), "tool_name": "Agent",
            "tool_input": {"prompt": prompt, "description": "Locate harness"},
        }

    def test_fenceless_spawn_is_allowed(self) -> None:
        self.assertIsNone(spawn_gate.handle(self.event("find the harness project")))

    def test_invalid_fence_is_allowed(self) -> None:
        bad = scope_fence({"write_scope": [], "stop_when": "done"})
        self.assertIsNone(spawn_gate.handle(self.event(bad)))

    def test_nothing_is_written_to_an_unmanaged_project(self) -> None:
        spawn_gate.handle(self.event("find the harness project"))
        self.assertFalse((self.root / ".gatekit").exists())

    def test_managed_project_still_denies(self) -> None:
        (self.root / ".gatekit").mkdir()
        self.assertIsNotNone(spawn_gate.handle(self.event("no fence here")))
