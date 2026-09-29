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


class TestHostAdapter(unittest.TestCase):
    """Codex speaks the same hook JSON as Claude Code except for the Stop
    block; the adapter renders per host and nothing else changes."""

    def test_default_host_is_claude(self) -> None:
        self.assertEqual(hookio.host_from_argv([]), "claude")

    def test_host_flag_is_read(self) -> None:
        self.assertEqual(hookio.host_from_argv(["--host", "codex"]), "codex")

    def test_unknown_host_falls_back_to_claude(self) -> None:
        self.assertEqual(hookio.host_from_argv(["--host", "vim"]), "claude")

    def test_hosts_constant(self) -> None:
        self.assertEqual(hookio.HOSTS, ("claude", "codex"))

    def test_stop_block_rendered_for_codex(self) -> None:
        payload = hookio.adapt_output(hookio.block_stop("not done"), "codex")
        self.assertEqual(payload, {"continue": False, "stopReason": "not done"})

    def test_stop_block_unchanged_for_claude(self) -> None:
        payload = hookio.adapt_output(hookio.block_stop("not done"), "claude")
        self.assertEqual(payload, {"decision": "block", "reason": "not done"})

    def test_deny_and_context_unchanged_for_codex(self) -> None:
        deny = hookio.deny("no")
        ctx = hookio.add_context("hi")
        self.assertEqual(hookio.adapt_output(deny, "codex"), deny)
        self.assertEqual(hookio.adapt_output(ctx, "codex"), ctx)

    def test_none_stays_none(self) -> None:
        self.assertIsNone(hookio.adapt_output(None, "codex"))

    def test_run_applies_host_from_explicit_argument(self) -> None:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            hookio.run(lambda e: hookio.block_stop("x"), stdin=io.StringIO("{}"), exit_process=False, host="codex")
        self.assertEqual(json.loads(buf.getvalue()), {"continue": False, "stopReason": "x"})


class TestHostCommandNames(unittest.TestCase):
    def test_codex_reasons_use_skill_syntax(self) -> None:
        deny = hookio.deny("run the /gatekit:gate pipeline")
        out = hookio.adapt_output(deny, "codex")
        self.assertIn("$gatekit-gate", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertNotIn("/gatekit:", json.dumps(out))

    def test_codex_context_and_stop_reason_rewritten(self) -> None:
        ctx = hookio.adapt_output(hookio.add_context("next: /gatekit:verify"), "codex")
        self.assertIn("$gatekit-verify", ctx["hookSpecificOutput"]["additionalContext"])
        stop = hookio.adapt_output(hookio.block_stop("run /gatekit:build again"), "codex")
        self.assertIn("$gatekit-build", stop["stopReason"])

    def test_claude_reasons_untouched(self) -> None:
        deny = hookio.deny("run the /gatekit:gate pipeline")
        self.assertEqual(hookio.adapt_output(deny, "claude"), deny)
