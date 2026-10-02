"""Tests for gates/release.py — a scope is dropped when its agent ends.

The event payloads are the ones recorded by the probe of 2026-10-02
(ADR-0022, ``tmp/probe-subagent-stop.md``), trimmed to the keys Claude Code
sent and with ``cwd`` pointed at this test's project.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import ledger  # noqa: E402
from gatekit.gates import release as release_gate  # noqa: E402
from gatekit.gates import spawn as spawn_gate  # noqa: E402
from tests import isolation  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "release.py"

SESSION = "adde5114-394f-4434-aaae-8c39f2a26314"
CALL_A, AGENT_A = "toolu_01Pev69ATZ7soRgV9c7aKSWx", "a548d2c64c28c74d0"
CALL_B, AGENT_B = "toolu_019RgKbXHZqdZQoTNmpM51ku", "aee89e4f2cde09bff"


def fenced(scope) -> str:
    return "work\n```gatekit-scope\n" + json.dumps(
        {"write_scope": scope, "stop_when": "tests pass"}) + "\n```"


class ReleaseProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- the measured event shapes ---------------------------------------
    def base(self, name: str) -> dict:
        return {
            "session_id": SESSION,
            "transcript_path": str(self.root / "transcript.jsonl"),
            "cwd": str(self.root),
            "prompt_id": "9eb2efae-8799-4aef-930b-f01118d69195",
            "permission_mode": "default",
            "hook_event_name": name,
        }

    def tool_input(self, description: str, scope, background) -> dict:
        tool_input = {"description": description, "prompt": fenced(scope),
                      "subagent_type": "general-purpose"}
        if background is not None:
            tool_input["run_in_background"] = background
        return tool_input

    def pre(self, call: str, description: str, scope, background=True, tool: str = "Agent") -> dict:
        event = self.base("PreToolUse")
        event.update({"tool_name": tool, "tool_use_id": call,
                      "tool_input": self.tool_input(description, scope, background)})
        return event

    def post_launched(self, call: str, agent: str, description: str, scope,
                      tool: str = "Agent") -> dict:
        """PostToolUse of a background agent: fires right after the launch."""
        event = self.base("PostToolUse")
        event.update({
            "tool_name": tool, "tool_use_id": call, "duration_ms": 6,
            "tool_input": self.tool_input(description, scope, True),
            "tool_response": {"isAsync": True, "status": "async_launched", "agentId": agent,
                              "description": description, "prompt": fenced(scope),
                              "outputFile": "C:\\x\\tasks\\%s.output" % agent,
                              "canReadOutputFile": True},
        })
        return event

    def post_completed(self, call: str, agent: str, description: str, scope) -> dict:
        """PostToolUse of a foreground agent: fires when the agent has ended."""
        event = self.base("PostToolUse")
        event.update({
            "tool_name": "Agent", "tool_use_id": call, "duration_ms": 2803,
            "tool_input": self.tool_input(description, scope, False),
            "tool_response": {"status": "completed", "prompt": fenced(scope), "agentId": agent,
                              "agentType": "general-purpose",
                              "content": [{"type": "text", "text": "DONE"}],
                              "totalDurationMs": 2801, "totalToolUseCount": 0},
        })
        return event

    def stop(self, agent: str, running=()) -> dict:
        event = self.base("SubagentStop")
        event.update({
            "agent_id": agent, "agent_type": "general-purpose", "stop_hook_active": False,
            "agent_transcript_path": str(self.root / ("agent-%s.jsonl" % agent)),
            "last_assistant_message": "DONE",
            "background_tasks": [{"id": a, "type": "subagent", "status": "running",
                                  "description": "x", "agent_type": "general-purpose"}
                                 for a in running],
            "session_crons": [],
        })
        return event

    # -- helpers ---------------------------------------------------------
    def led(self) -> ledger.Ledger:
        return ledger.Ledger.load(self.root, SESSION)

    def owners(self) -> list:
        return [s["owner"] for s in self.led().data["scopes"]]

    def spawn(self, event: dict):
        return spawn_gate.handle(event)

    def fire(self, event: dict) -> None:
        """Call the hook and assert the one thing true of every call: no payload."""
        self.assertIsNone(release_gate.handle(event))

    def denied(self, result) -> bool:
        return (result is not None
                and result["hookSpecificOutput"]["permissionDecision"] == "deny")


class TestSpawnStoresTheCallId(ReleaseProject):
    def test_tool_use_id_is_stored_with_the_scope(self) -> None:
        self.assertIsNone(self.spawn(self.pre(CALL_A, "probe-bg-a", ["src/a/**"])))
        entry = self.led().data["scopes"][0]
        self.assertEqual(entry["tool_use_id"], CALL_A)
        self.assertNotIn("agent_id", entry)

    def test_spawn_without_a_call_id_still_records_the_scope(self) -> None:
        event = self.pre(CALL_A, "old", ["src/a/**"])
        del event["tool_use_id"]
        self.assertIsNone(self.spawn(event))
        self.assertNotIn("tool_use_id", self.led().data["scopes"][0])

    def test_the_lock_file_is_gone_after_the_gate(self) -> None:
        self.spawn(self.pre(CALL_A, "a", ["src/a/**"]))
        self.assertFalse(ledger.ScopeLock(self.root, SESSION).path.exists())


class TestBackgroundAgent(ReleaseProject):
    """PreToolUse, PostToolUse(async_launched) at once, SubagentStop at the end."""

    def setUp(self) -> None:
        super().setUp()
        self.spawn(self.pre(CALL_A, "probe-bg-a", ["src/a/**"]))
        self.spawn(self.pre(CALL_B, "probe-bg-b", ["src/b/**"]))

    def test_the_launch_event_releases_nothing(self) -> None:
        self.fire(self.post_launched(CALL_A, AGENT_A, "probe-bg-a", ["src/a/**"]))
        self.assertEqual(self.owners(), ["probe-bg-a", "probe-bg-b"])
        self.assertEqual(self.led().data["scopes"][0]["agent_id"], AGENT_A)
        # still running, so a second agent over the same files is still refused
        self.assertTrue(self.denied(self.spawn(self.pre("toolu_x", "again", ["src/a/**"]))))

    def test_stop_releases_exactly_that_agents_scope(self) -> None:
        self.fire(self.post_launched(CALL_A, AGENT_A, "probe-bg-a", ["src/a/**"]))
        self.fire(self.post_launched(CALL_B, AGENT_B, "probe-bg-b", ["src/b/**"]))
        self.fire(self.stop(AGENT_B, running=(AGENT_A, AGENT_B)))
        self.assertEqual(self.owners(), ["probe-bg-a"])
        self.assertTrue(self.denied(self.spawn(self.pre("toolu_x", "again", ["src/a/**"]))))
        self.assertIsNone(self.spawn(self.pre("toolu_y", "next-b", ["src/b/**"])))
        self.fire(self.stop(AGENT_A))
        self.assertEqual(self.owners(), ["next-b"])

    def test_release_is_recorded_as_an_event(self) -> None:
        self.fire(self.post_launched(CALL_A, AGENT_A, "probe-bg-a", ["src/a/**"]))
        self.fire(self.stop(AGENT_A))
        event = [e for e in self.led().data["events"] if e["kind"] == "scope_released"][-1]
        self.assertEqual(event["detail"]["by"], "agent_id")
        self.assertEqual(event["detail"]["id"], AGENT_A)
        self.assertEqual(event["detail"]["owners"], ["probe-bg-a"])

    def test_two_agents_with_the_same_description_stay_apart(self) -> None:
        self.spawn(self.pre("toolu_c", "probe-bg-a", ["src/c/**"]))  # same label as CALL_A
        self.fire(self.post_launched(CALL_A, AGENT_A, "probe-bg-a", ["src/a/**"]))
        self.fire(self.post_launched("toolu_c", "agent_c", "probe-bg-a", ["src/c/**"]))
        self.fire(self.stop("agent_c"))
        scopes = self.led().data["scopes"]
        self.assertEqual([s["write_scope"] for s in scopes], [["src/a/**"], ["src/b/**"]])

    def test_a_second_stop_for_the_same_agent_changes_nothing(self) -> None:
        self.fire(self.post_launched(CALL_A, AGENT_A, "probe-bg-a", ["src/a/**"]))
        self.fire(self.post_launched(CALL_B, AGENT_B, "probe-bg-b", ["src/b/**"]))
        self.fire(self.stop(AGENT_A))
        self.fire(self.stop(AGENT_A))
        self.assertEqual(self.owners(), ["probe-bg-b"])

    def test_stop_before_the_launch_event_still_releases(self) -> None:
        # The order was never observed for a background agent; if it happens,
        # the id waits in ended_agents and the binding releases at once.
        self.fire(self.stop(AGENT_A))
        self.assertEqual(self.owners(), ["probe-bg-a", "probe-bg-b"])
        self.fire(self.post_launched(CALL_A, AGENT_A, "probe-bg-a", ["src/a/**"]))
        self.assertEqual(self.owners(), ["probe-bg-b"])


class TestForegroundAgent(ReleaseProject):
    """PreToolUse, SubagentStop, then PostToolUse(completed)."""

    def setUp(self) -> None:
        super().setUp()
        self.spawn(self.pre(CALL_A, "probe-fg", ["src/a/**"], background=False))

    def test_stop_alone_does_not_release_an_unbound_scope(self) -> None:
        self.fire(self.stop(AGENT_A))
        self.assertEqual(self.owners(), ["probe-fg"])
        self.assertEqual(self.led().data["ended_agents"], [AGENT_A])

    def test_completed_tool_call_releases(self) -> None:
        self.fire(self.stop(AGENT_A))
        self.fire(self.post_completed(CALL_A, AGENT_A, "probe-fg", ["src/a/**"]))
        self.assertEqual(self.owners(), [])
        event = [e for e in self.led().data["events"] if e["kind"] == "scope_released"][-1]
        self.assertEqual(event["detail"]["by"], "tool_use_id")
        self.assertIsNone(self.spawn(self.pre("toolu_next", "round-2", ["src/a/**"])))

    def test_completed_without_a_prior_stop_releases(self) -> None:
        self.fire(self.post_completed(CALL_A, AGENT_A, "probe-fg", ["src/a/**"]))
        self.assertEqual(self.owners(), [])

    def test_task_tool_name_is_handled_like_agent(self) -> None:
        event = self.post_completed(CALL_A, AGENT_A, "probe-fg", ["src/a/**"])
        event["tool_name"] = "Task"
        self.fire(event)
        self.assertEqual(self.owners(), [])


class TestNothingIsGuessed(ReleaseProject):
    def setUp(self) -> None:
        super().setUp()
        self.spawn(self.pre(CALL_A, "probe-bg-a", ["src/a/**"]))
        self.fire(self.post_launched(CALL_A, AGENT_A, "probe-bg-a", ["src/a/**"]))

    def assert_kept(self) -> None:
        self.assertEqual(self.owners(), ["probe-bg-a"])

    def test_unknown_agent_id_releases_nothing(self) -> None:
        self.fire(self.stop("someone_else"))
        self.assert_kept()
        self.assertEqual(self.led().data["ended_agents"], [])  # no scope was waiting

    def test_unknown_tool_use_id_releases_nothing(self) -> None:
        self.fire(self.post_completed("toolu_other", "x", "probe-bg-a", ["src/a/**"]))
        self.assert_kept()

    def test_same_description_and_prompt_do_not_release(self) -> None:
        event = self.post_completed("toolu_other", AGENT_A, "probe-bg-a", ["src/a/**"])
        self.fire(event)
        self.assert_kept()

    def test_other_session_releases_nothing(self) -> None:
        event = self.stop(AGENT_A)
        event["session_id"] = "another-session"
        self.fire(event)
        self.assert_kept()
        self.assertFalse(ledger.Ledger.exists(self.root, "another-session"))

    def test_other_events_and_tools_release_nothing(self) -> None:
        post = self.post_completed(CALL_A, AGENT_A, "probe-bg-a", ["src/a/**"])
        for change in ({"hook_event_name": "PreToolUse"}, {"hook_event_name": "Stop"},
                       {"hook_event_name": "SubagentStart"}, {"tool_name": "Bash"},
                       {"hook_event_name": None}):
            with self.subTest(change=change):
                self.fire(dict(post, **change))
                self.assert_kept()
        start = dict(self.stop(AGENT_A), hook_event_name="SubagentStart")
        self.fire(start)
        self.assert_kept()

    def test_malformed_input_releases_nothing(self) -> None:
        stop = self.stop(AGENT_A)
        post = self.post_completed(CALL_A, AGENT_A, "probe-bg-a", ["src/a/**"])
        for event in (dict(stop, agent_id=None), dict(stop, agent_id=""), dict(stop, agent_id=7),
                      dict(stop, agent_id=[AGENT_A]), dict(post, tool_use_id=None),
                      dict(post, tool_use_id=""), dict(post, tool_response="completed"),
                      dict(post, tool_response=None), {}):
            with self.subTest(event=event):
                self.fire(event)
                self.assert_kept()

    def test_launch_status_never_releases_whatever_else_it_says(self) -> None:
        self.spawn(self.pre(CALL_B, "probe-bg-b", ["src/b/**"]))
        event = self.post_launched(CALL_B, AGENT_B, "probe-bg-b", ["src/b/**"])
        event["tool_response"]["status"] = "completed"   # contradicts isAsync
        self.fire(event)
        self.assertEqual(self.owners(), ["probe-bg-a", "probe-bg-b"])

    def test_a_held_lock_means_no_change(self) -> None:
        lock = ledger.ScopeLock(self.root, SESSION)
        with lock as held:
            self.assertTrue(held)
            original = ledger.ScopeLock.__init__.__defaults__
            ledger.ScopeLock.__init__.__defaults__ = (0.05, 15.0)
            try:
                self.fire(self.stop(AGENT_A))
            finally:
                ledger.ScopeLock.__init__.__defaults__ = original
        self.assert_kept()
        self.fire(self.stop(AGENT_A))
        self.assertEqual(self.owners(), [])


class TestUnmanaged(ReleaseProject):
    def test_project_without_gatekit_gets_no_state(self) -> None:
        (self.root / ".gatekit").rmdir()
        self.fire(self.stop(AGENT_A))
        self.fire(self.post_completed(CALL_A, AGENT_A, "x", ["src/a/**"]))
        self.assertFalse((self.root / ".gatekit").exists())

    def test_session_without_a_ledger_gets_none(self) -> None:
        self.fire(self.stop(AGENT_A))
        self.assertFalse(ledger.Ledger.exists(self.root, SESSION))
        self.assertEqual(list((self.root / ".gatekit").iterdir()), [])


class TestSubprocess(ReleaseProject):
    def run_gate(self, stdin: str) -> subprocess.CompletedProcess:
        """The gate as a process whose working directory is this test's project.

        An event without a usable ``cwd`` sends the gate to its process's
        working directory. Left at the test runner's own, that is this
        repository, and the gate wrote to its real ``.gatekit/runs/``.
        """
        env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
        return isolation.run_gate([sys.executable, str(GATE_SCRIPT)], cwd=self.root, input=stdin,
                                  capture_output=True, text=True, timeout=60, env=env)

    def test_release_via_subprocess_prints_nothing(self) -> None:
        self.spawn(self.pre(CALL_A, "probe-bg-a", ["src/a/**"]))
        for event in (self.post_launched(CALL_A, AGENT_A, "probe-bg-a", ["src/a/**"]),
                      self.stop(AGENT_A)):
            proc = self.run_gate(json.dumps(event))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout, "")
        self.assertEqual(self.owners(), [])

    def test_corrupt_scope_lists_exit_zero_and_leave_no_lock(self) -> None:
        self.spawn(self.pre(CALL_A, "probe-bg-a", ["src/a/**"]))
        path = ledger.Ledger.path_for(self.root, SESSION)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["scopes"] = {"not": "a list"}
        data["ended_agents"] = 5
        path.write_text(json.dumps(data), encoding="utf-8")
        runs = self.root / ".gatekit" / "runs"
        runs_lock = ledger.ScopeLock(self.root, SESSION).path
        proc = self.run_gate(json.dumps(self.stop(AGENT_A)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertFalse(runs_lock.exists())
        self.assertTrue(runs.is_dir())

    def test_handler_exception_is_logged_and_exits_zero(self) -> None:
        self.spawn(self.pre(CALL_A, "probe-bg-a", ["src/a/**"]))
        event = self.stop(AGENT_A)
        event["cwd"] = 12345  # not a path: the handler raises before any work
        log = self.root / ".gatekit" / "runs" / "hook-errors.log"
        self.assertFalse(log.exists())
        proc = self.run_gate(json.dumps(event))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")
        # The event names no project, so the line goes to the one the process stands in.
        lines = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("SubagentStop", lines[0])
        self.assertIn("TypeError", lines[0])
        self.assertEqual(self.owners(), ["probe-bg-a"])  # nothing was released

    def test_empty_and_malformed_stdin_exit_zero(self) -> None:
        for stdin in ("", "{not json", "[1, 2]", "null"):
            with self.subTest(stdin=stdin):
                proc = self.run_gate(stdin)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout, "")
        self.assertEqual(list((self.root / ".gatekit").iterdir()), [])  # and no state


if __name__ == "__main__":
    unittest.main()
