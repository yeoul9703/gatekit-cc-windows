"""Tests for gatekit.hookio — the hook stdin/stdout contract.

Output shapes verified against the official Claude Code hooks documentation
(code.claude.com/docs/en/hooks) on 2026-09-10; they match ARCHITECTURE.md §3.
"""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import hookio


class TestPayloadShapes(unittest.TestCase):
    def test_deny_shape(self) -> None:
        payload = hookio.deny("nope")
        self.assertEqual(
            payload,
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "nope",
                }
            },
        )

    def test_block_stop_shape_is_top_level_decision(self) -> None:
        payload = hookio.block_stop("criteria failing")
        self.assertEqual(payload, {"decision": "block", "reason": "criteria failing"})

    def test_add_context_shape_is_nested(self) -> None:
        payload = hookio.add_context("lang=en")
        self.assertEqual(
            payload,
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": "lang=en",
                }
            },
        )

    def test_add_context_nests_under_hook_specific_output(self) -> None:
        # A root-level additionalContext is ignored by Claude Code.
        self.assertNotIn("additionalContext", hookio.add_context("x"))

    def test_add_context_truncates_to_limit(self) -> None:
        payload = hookio.add_context("x" * 5000)
        text = payload["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(text), hookio.MAX_CONTEXT_CHARS)

    def test_add_context_empty_returns_none(self) -> None:
        self.assertIsNone(hookio.add_context(""))
        self.assertIsNone(hookio.add_context("   "))

    def test_allow_is_none(self) -> None:
        self.assertIsNone(hookio.allow())

    def test_payloads_are_json_serializable(self) -> None:
        for payload in (hookio.deny("r"), hookio.block_stop("r"), hookio.add_context("c")):
            json.dumps(payload)


class TestReadEvent(unittest.TestCase):
    def test_reads_json_object(self) -> None:
        event = hookio.read_event(io.StringIO('{"session_id":"s","tool_name":"Write"}'))
        self.assertEqual(event["session_id"], "s")

    def test_empty_stdin_is_empty_dict(self) -> None:
        self.assertEqual(hookio.read_event(io.StringIO("")), {})

    def test_malformed_json_is_empty_dict(self) -> None:
        self.assertEqual(hookio.read_event(io.StringIO("{oops")), {})

    def test_non_object_json_is_empty_dict(self) -> None:
        self.assertEqual(hookio.read_event(io.StringIO("[1,2]")), {})


class TestRun(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        self.event = {"session_id": "s", "hook_event_name": "PreToolUse", "cwd": str(self.root)}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, handler) -> "tuple[str, int]":
        stdin = io.StringIO(json.dumps(self.event))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = hookio.run(handler, stdin=stdin, exit_process=False)
        return buf.getvalue(), code

    def test_handler_none_prints_nothing_and_exits_zero(self) -> None:
        out, code = self._run(lambda event: None)
        self.assertEqual(out, "")
        self.assertEqual(code, 0)

    def test_handler_payload_is_printed_as_json(self) -> None:
        out, code = self._run(lambda event: hookio.deny("because"))
        self.assertEqual(code, 0)
        parsed = json.loads(out)
        self.assertEqual(parsed["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_handler_receives_the_event(self) -> None:
        seen = {}

        def handler(event):
            seen.update(event)
            return None

        self._run(handler)
        self.assertEqual(seen["session_id"], "s")

    def test_exception_still_exits_zero_and_prints_nothing(self) -> None:
        def boom(event):
            raise RuntimeError("gate exploded")

        out, code = self._run(boom)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_exception_is_logged_one_line(self) -> None:
        def boom(event):
            raise RuntimeError("gate exploded")

        self._run(boom)
        log = self.root / ".gatekit" / "runs" / "hook-errors.log"
        self.assertTrue(log.is_file())
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("PreToolUse", lines[0])
        self.assertIn("gate exploded", lines[0])

    def test_repeated_errors_append(self) -> None:
        def boom(event):
            raise ValueError("x")

        self._run(boom)
        self._run(boom)
        log = self.root / ".gatekit" / "runs" / "hook-errors.log"
        self.assertEqual(len(log.read_text(encoding="utf-8").strip().splitlines()), 2)

    def test_keyboard_interrupt_also_exits_zero(self) -> None:
        def boom(event):
            raise KeyboardInterrupt()

        _, code = self._run(boom)
        self.assertEqual(code, 0)

    def test_unserializable_payload_exits_zero(self) -> None:
        out, code = self._run(lambda event: {"bad": object()})
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_multiline_error_is_flattened_to_one_line(self) -> None:
        def boom(event):
            raise RuntimeError("line one\nline two")

        self._run(boom)
        log = self.root / ".gatekit" / "runs" / "hook-errors.log"
        self.assertEqual(len(log.read_text(encoding="utf-8").strip().splitlines()), 1)


class TestRunWithACwdThatIsNotText(unittest.TestCase):
    """The event itself can be what breaks a gate: a ``cwd`` that is not a string makes
    ``event_root`` raise. The failure path asked ``event_root`` again, failed the same way and
    left no line. It must leave its line, in the project of the process's own working
    directory, and still allow."""

    BROKEN_CWDS = (1, True, 1.5, ["a"], {"x": 1})

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        self.log = self.root / ".gatekit" / "runs" / "hook-errors.log"
        # Registered after the folder's cleanup, so it runs first: the folder cannot be
        # removed while it is the working directory.
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.root)

    def _run(self, handler, event) -> "tuple[str, int]":
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = hookio.run(handler, stdin=io.StringIO(json.dumps(event)), exit_process=False)
        return buf.getvalue(), code

    def _lines(self) -> list:
        return self.log.read_text(encoding="utf-8").strip().splitlines() if self.log.is_file() else []

    def test_the_event_root_fault_is_logged_and_the_gate_allows(self) -> None:
        # What every gate does first: resolve the project from the event.
        for count, cwd in enumerate(self.BROKEN_CWDS, start=1):
            with self.subTest(cwd=cwd):
                with self.assertRaises(TypeError):
                    hookio.event_root({"cwd": cwd})
                out, code = self._run(lambda event: hookio.event_root(event) and None,
                                      {"hook_event_name": "PreToolUse", "cwd": cwd})
                self.assertEqual((out, code), ("", 0))
                lines = self._lines()
                self.assertEqual(len(lines), count, lines)
                self.assertIn("PreToolUse", lines[-1])
                self.assertIn("TypeError", lines[-1])

    def test_a_handler_fault_is_logged_whatever_the_cwd_is(self) -> None:
        def boom(event):
            raise RuntimeError("gate exploded")

        out, code = self._run(boom, {"hook_event_name": "Stop", "cwd": ["not", "a", "path"]})
        self.assertEqual((out, code), ("", 0))
        lines = self._lines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("Stop", lines[0])
        self.assertIn("gate exploded", lines[0])

    def test_a_text_cwd_still_decides_where_the_line_goes(self) -> None:
        # The usual path is unchanged: the line goes to the project of the event's cwd,
        # not to the one the process happens to stand in.
        def boom(event):
            raise RuntimeError("gate exploded")

        with tempfile.TemporaryDirectory() as other:
            other_root = pathlib.Path(os.path.realpath(other))
            (other_root / ".gatekit").mkdir()
            self._run(boom, {"hook_event_name": "PreToolUse", "cwd": str(other_root)})
            self.assertTrue((other_root / ".gatekit" / "runs" / "hook-errors.log").is_file())
        self.assertEqual(self._lines(), [])

    def test_a_hook_process_exits_zero_prints_nothing_and_leaves_the_line(self) -> None:
        # The same through a real process, the way Claude Code starts a hook: JSON on stdin,
        # the project folder as the working directory, sys.exit at the end.
        kit = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = ("import sys; sys.path.insert(0, %r); from gatekit import hookio; "
                "hookio.run(lambda event: hookio.event_root(event) and None)" % kit)
        proc = subprocess.run([sys.executable, "-c", code], cwd=str(self.root),
                              input=json.dumps({"hook_event_name": "PreToolUse", "cwd": 1}),
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertNotIn("Traceback", proc.stderr)
        lines = self._lines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("PreToolUse", lines[0])
        self.assertIn("TypeError", lines[0])


class TestResultIsUtf8OnAnyConsole(unittest.TestCase):
    """A Korean denial must reach the caller even when the console is cp1252.

    Written through ``sys.stdout`` it raised ``UnicodeEncodeError``, ``run``
    swallowed that, and the gate printed nothing: a denial became an allow.
    """

    def test_a_korean_reason_is_written_as_utf8_under_a_cp1252_console(self) -> None:
        kit = pathlib.Path(__file__).resolve().parents[1]
        code = (
            "import sys; sys.path.insert(0, %r)\n"
            "from gatekit import hookio\n"
            "hookio.run(lambda event: hookio.deny('\\uc774 \\ud30c\\uc77c\\uc740 \\ub9c9\\ud600 \\uc788\\uc2b5\\ub2c8\\ub2e4'))\n"
        ) % str(kit)
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        env["PYTHONIOENCODING"] = "cp1252"
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, "-c", code], input=b"{}", cwd=tmp,
                                  capture_output=True, env=env, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout.decode("utf-8"))
        reason = payload["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("이 파일은 막혀 있습니다", reason)


class TestLogError(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_creates_runs_dir(self) -> None:
        hookio.log_error(self.root, "Stop", RuntimeError("boom"))
        self.assertTrue((self.root / ".gatekit" / "runs" / "hook-errors.log").is_file())

    def test_never_raises_on_unwritable_root(self) -> None:
        # A path that cannot be created must not propagate out of a gate.
        hookio.log_error(pathlib.Path("/proc/nonexistent-gatekit"), "Stop", RuntimeError("x"))


class TestHelpers(unittest.TestCase):
    def test_event_root_prefers_cwd_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(os.path.realpath(tmp))
            (root / ".gatekit").mkdir()
            nested = root / "src"
            nested.mkdir()
            found = hookio.event_root({"cwd": str(nested)})
            self.assertEqual(found, root)

    def test_event_root_without_cwd_uses_process_cwd(self) -> None:
        self.assertIsInstance(hookio.event_root({}), pathlib.Path)

    def test_session_id_defaults_to_placeholder(self) -> None:
        self.assertTrue(hookio.session_id({}))
        self.assertEqual(hookio.session_id({"session_id": "abc"}), "abc")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
