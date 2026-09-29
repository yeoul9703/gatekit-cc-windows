"""Tests for gatekit.workers — backend registry, unsafe-flag rule, probes."""
from __future__ import annotations

import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import config, verdict, workers


def write_config(root: pathlib.Path, cfg: dict) -> None:
    state = root / ".gatekit"
    state.mkdir(parents=True, exist_ok=True)
    (state / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


def make_stub_binary(directory: pathlib.Path, name: str, exit_code: int = 0,
                     body: str = "stub 1.2.3") -> pathlib.Path:
    """A tiny shell script that prints `body` and exits `exit_code`."""
    path = directory / name
    path.write_text("#!/bin/sh\necho '%s'\nexit %d\n" % (body, exit_code), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class WorkerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        self._bin = tempfile.TemporaryDirectory()
        self.bindir = pathlib.Path(os.path.realpath(self._bin.name))
        self._old_path = os.environ.get("PATH", "")
        # PATH is *replaced*, not prepended: a real `claude` binary on the
        # developer's machine must not decide the outcome of these tests.
        os.environ["PATH"] = str(self.bindir)

    def tearDown(self) -> None:
        os.environ["PATH"] = self._old_path
        self._bin.cleanup()
        self._tmp.cleanup()


class TestResolve(WorkerTestCase):
    def test_default_is_claude_with_documented_argv(self) -> None:
        backend = workers.resolve(self.root)
        self.assertEqual(backend["name"], "claude")
        self.assertEqual(backend["argv"][:2], ["claude", "-p"])
        self.assertIn("--output-format", backend["argv"])
        self.assertIn("--permission-mode", backend["argv"])
        self.assertFalse(backend["unsafe"])

    def test_disabled_backend_raises(self) -> None:
        write_config(self.root, {"worker": {"backends": {
            "other": {"argv": ["other"], "enabled": False}}}})
        with self.assertRaises(ValueError) as ctx:
            workers.resolve(self.root, "other")
        self.assertIn("disabled", str(ctx.exception))

    def test_unknown_backend_raises(self) -> None:
        with self.assertRaises(ValueError):
            workers.resolve(self.root, "nope")

    def test_empty_argv_raises(self) -> None:
        write_config(self.root, {"worker": {"backends": {"bad": {"argv": [], "enabled": True}}}})
        with self.assertRaises(ValueError):
            workers.resolve(self.root, "bad")

    def test_bypass_flag_without_unsafe_raises(self) -> None:
        for flag in ("--dangerously-skip-permissions", "--permission-mode=bypassPermissions",
                     "--yolo"):
            write_config(self.root, {"worker": {"backends": {
                "risky": {"argv": ["claude", flag], "enabled": True}}}})
            with self.assertRaises(ValueError, msg=flag) as ctx:
                workers.resolve(self.root, "risky")
            self.assertIn("bypass", str(ctx.exception))

    def test_bypass_flag_with_unsafe_true_resolves(self) -> None:
        write_config(self.root, {"worker": {"backends": {"risky": {
            "argv": ["claude", "--dangerously-skip-permissions"],
            "enabled": True, "unsafe": True}}}})
        backend = workers.resolve(self.root, "risky")
        self.assertTrue(backend["unsafe"])


class TestCheck(WorkerTestCase):
    def test_missing_executable_is_fail(self) -> None:
        result = workers.check(self.root, "claude")
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("PATH", result["detail"])

    def test_present_executable_with_version_is_ok(self) -> None:
        make_stub_binary(self.bindir, "claude", 0, "1.2.3 (Claude Code)")
        result = workers.check(self.root, "claude")
        self.assertEqual(result["verdict"], verdict.OK)
        self.assertIn("1.2.3", result["detail"])

    def test_failing_version_probe_is_unverified_not_fail(self) -> None:
        make_stub_binary(self.bindir, "claude", 3, "boom")
        result = workers.check(self.root, "claude")
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)

    def test_unknown_backend_is_fail(self) -> None:
        self.assertEqual(workers.check(self.root, "ghost")["verdict"], verdict.FAIL)


class TestCli(WorkerTestCase):
    def test_list_json_marks_default_and_states(self) -> None:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(workers.run(["list", "--json", "--root", str(self.root)]), 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["default"], "claude")
        by_name = {b["name"]: b for b in payload["backends"]}
        self.assertTrue(by_name["claude"]["enabled"])

    def test_enable_then_set_default_persists(self) -> None:
        import contextlib
        import io

        write_config(self.root, {"worker": {"backends": {
            "other": {"argv": ["other"], "enabled": False}}}})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workers.run(["enable", "other", "--root", str(self.root)]), 0)
            self.assertEqual(workers.run(["set-default", "other", "--root", str(self.root)]), 0)
        cfg = config.load(self.root)
        self.assertTrue(cfg["worker"]["backends"]["other"]["enabled"])
        self.assertEqual(cfg["worker"]["default"], "other")
        self.assertEqual(workers.resolve(self.root)["name"], "other")

    def test_enable_refuses_unsafe_backend_without_opt_in(self) -> None:
        import contextlib
        import io

        write_config(self.root, {"worker": {"backends": {
            "risky": {"argv": ["claude", "--dangerously-skip-permissions"], "enabled": False}}}})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = workers.run(["enable", "risky", "--root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertFalse(config.load(self.root)["worker"]["backends"]["risky"]["enabled"])

    def test_check_missing_binary_exits_1(self) -> None:
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workers.run(["check", "claude", "--root", str(self.root)]), 1)


if __name__ == "__main__":
    unittest.main()


class TestReadOnlyArgv(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_defaults_carry_read_only_argv(self) -> None:
        from gatekit import config
        claude = config.DEFAULTS["worker"]["backends"]["claude"]["read_only_argv"]
        self.assertIn("plan", claude)
        self.assertNotIn("acceptEdits", claude)

    def test_default_evaluator_is_unset(self) -> None:
        """ADR-0013 decision 2 replaced the `agent` default with an empty one.

        `agent` as a *default* meant the host's own subagent graded the host's
        own output unless someone changed it, and on gk-trial2 nobody did.
        Unset resolves at call time to a backend that is not the host; `agent`
        remains available as an explicit choice.
        """
        from gatekit import config
        self.assertEqual(config.DEFAULTS["verify"]["evaluator"], "")

    def test_resolve_read_only_uses_read_only_argv(self) -> None:
        backend = workers.resolve(self.root, "claude", read_only=True)
        self.assertIn("plan", backend["argv"])
        self.assertTrue(backend["read_only"])

    def test_resolve_read_only_without_read_only_argv_raises(self) -> None:
        cfg = {"worker": {"backends": {"bare": {"argv": ["x"], "enabled": True}}}}
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        with self.assertRaises(ValueError):
            workers.resolve(self.root, "bare", read_only=True)

    def test_resolve_read_only_still_rejects_bypass_flags(self) -> None:
        cfg = {"worker": {"backends": {"bad": {"argv": ["x"], "read_only_argv": ["x", "--dangerously-skip"], "enabled": True}}}}
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        with self.assertRaises(ValueError):
            workers.resolve(self.root, "bad", read_only=True)

    def test_set_evaluator_persists(self) -> None:
        from gatekit import config
        self.assertEqual(workers.run(["set-evaluator", "claude", "--root", str(self.root)]), 0)
        self.assertEqual(config.load(self.root)["verify"]["evaluator"], "claude")
        self.assertEqual(workers.run(["set-evaluator", "agent", "--root", str(self.root)]), 0)
        self.assertEqual(config.load(self.root)["verify"]["evaluator"], "agent")

    def test_set_evaluator_rejects_unknown(self) -> None:
        self.assertNotEqual(workers.run(["set-evaluator", "vim", "--root", str(self.root)]), 0)

    def test_evaluator_name_helper(self) -> None:
        self.assertEqual(workers.evaluator_name(self.root), "agent")


class TestProbe(WorkerTestCase):
    """`workers check --probe` runs the backend once with a trivial prompt, so
    a binary that exists but cannot answer (not logged in, sandboxed away from
    its credentials) is caught before a build, not by the build."""

    def stub_probe(self, exit_code: int, body: str, sleep: float = 0) -> None:
        path = self.bindir / "claude"
        path.write_text(
            "#!/bin/sh\n/bin/cat >/dev/null\n/bin/sleep %s\necho '%s'\nexit %d\n" % (sleep, body, exit_code),
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def test_probe_ok_when_backend_answers(self) -> None:
        self.stub_probe(0, "READY")
        result = workers.check(self.root, "claude", probe=True)
        self.assertEqual(result["verdict"], verdict.OK)
        self.assertIn("probe", result["detail"])

    def test_probe_fail_when_backend_cannot_run_a_prompt(self) -> None:
        self.stub_probe(1, "Not logged in · Please run /login")
        result = workers.check(self.root, "claude", probe=True)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("Not logged in", result["detail"])

    def test_probe_timeout_is_unverified(self) -> None:
        self.stub_probe(0, "late", sleep=3)
        workers.PROBE_TIMEOUT_S = 1.0
        try:
            result = workers.check(self.root, "claude", probe=True)
        finally:
            workers.PROBE_TIMEOUT_S = 60.0
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)

    def test_probe_uses_read_only_argv(self) -> None:
        path = self.bindir / "claude"
        path.write_text("#!/bin/sh\n/bin/cat >/dev/null\necho \"$@\"\nexit 0\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        result = workers.check(self.root, "claude", probe=True)
        self.assertIn("plan", result["detail"])
        self.assertNotIn("acceptEdits", result["detail"])

    def test_probe_not_run_without_flag(self) -> None:
        self.stub_probe(1, "Not logged in")
        # --version probe of the same stub exits 1 -> unverified, not fail
        result = workers.check(self.root, "claude")
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)

    def test_cli_probe_flag(self) -> None:
        import contextlib, io
        self.stub_probe(1, "Not logged in")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = workers.run(["check", "claude", "--probe", "--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("fail", buf.getvalue())


# ------------------------ ADR-0013 decision 2: the grader is another model


class TestEvaluatorDefault(unittest.TestCase):
    """On gk-trial2 `verify.evaluator` was left at `agent`, so Claude graded
    Claude — the failure ADR-0007 exists to prevent, reached by leaving a
    default alone. An unset evaluator now resolves to an enabled backend whose
    name differs from the host."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_cfg(self, cfg: dict) -> None:
        (self.root / ".gatekit" / "config.json").write_text(
            json.dumps(cfg), encoding="utf-8")

    def test_unset_resolves_to_an_enabled_other_backend(self) -> None:
        self.write_cfg({"worker": {"default": "claude", "backends": {
            "claude": {"argv": ["claude"], "read_only_argv": ["claude"], "enabled": True},
            "other": {"argv": ["other"], "read_only_argv": ["other"], "enabled": True}}}})
        self.assertEqual(workers.evaluator_name(self.root, host="claude"), "other")

    def test_an_explicit_setting_always_wins(self) -> None:
        self.write_cfg({"verify": {"evaluator": "agent"},
                        "worker": {"default": "claude", "backends": {
                            "other": {"argv": ["other"], "read_only_argv": ["other"],
                                      "enabled": True}}}})
        self.assertEqual(workers.evaluator_name(self.root, host="claude"), "agent")

    def test_a_disabled_other_backend_is_not_chosen(self) -> None:
        self.write_cfg({"worker": {"default": "claude", "backends": {
            "claude": {"argv": ["claude"], "read_only_argv": ["claude"], "enabled": True},
            "other": {"argv": ["other"], "read_only_argv": ["other"], "enabled": False}}}})
        self.assertEqual(workers.evaluator_name(self.root, host="claude"), "agent")

    def test_a_backend_without_read_only_argv_cannot_grade(self) -> None:
        self.write_cfg({"worker": {"default": "claude", "backends": {
            "claude": {"argv": ["claude"], "read_only_argv": ["claude"], "enabled": True},
            "other": {"argv": ["other"], "enabled": True}}}})
        self.assertEqual(workers.evaluator_name(self.root, host="claude"), "agent")

    def test_the_host_never_grades_itself(self) -> None:
        """An `other`-hosted project grades with Claude, not `other` — the
        rule is symmetric. `config.DEFAULTS` always carries an enabled
        `claude` backend, so this is a realistic shape."""
        self.write_cfg({"worker": {"default": "other", "backends": {
            "other": {"argv": ["other"], "read_only_argv": ["other"], "enabled": True}}}})
        self.assertEqual(workers.evaluator_name(self.root, host="other"), "claude")

    def test_agent_only_when_every_backend_is_the_host(self) -> None:
        self.write_cfg({"worker": {"default": "claude", "backends": {
            "claude": {"argv": ["claude"], "read_only_argv": ["claude"], "enabled": True},
            "other": {"enabled": False}}}})
        self.assertEqual(workers.evaluator_name(self.root, host="claude"), "agent")

    def test_falling_back_to_agent_is_reported(self) -> None:
        self.write_cfg({"worker": {"default": "claude", "backends": {
            "claude": {"argv": ["claude"], "read_only_argv": ["claude"], "enabled": True}}}})
        name, why = workers.evaluator_choice(self.root, host="claude")
        self.assertEqual(name, "agent")
        self.assertIn("same model", why.lower())

    def test_choosing_another_backend_says_so(self) -> None:
        self.write_cfg({"worker": {"default": "claude", "backends": {
            "claude": {"argv": ["claude"], "read_only_argv": ["claude"], "enabled": True},
            "other": {"argv": ["other"], "read_only_argv": ["other"], "enabled": True}}}})
        name, why = workers.evaluator_choice(self.root, host="claude")
        self.assertEqual(name, "other")
        self.assertEqual(why, "")
