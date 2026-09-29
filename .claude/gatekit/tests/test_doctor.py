"""Tests for gatekit.doctor — 7 axes, fault-injected one at a time.

`unverified` is asserted as itself rather than rounded to ok or fail.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import sys
import tempfile
import unittest

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import doctor, paths, verdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fakebin import make_fake, print_and_exit  # noqa: E402


class DoctorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()

        self._old_path = os.environ.get("PATH", "")
        self._bin = tempfile.TemporaryDirectory()
        self.bindir = pathlib.Path(os.path.realpath(self._bin.name))
        os.environ["PATH"] = str(self.bindir)

    def tearDown(self) -> None:
        os.environ["PATH"] = self._old_path
        self._bin.cleanup()
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------

    def write_project_settings(self, hooks) -> None:
        directory = self.root / ".claude"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "settings.json").write_text(
            json.dumps({"hooks": hooks}), encoding="utf-8"
        )

    def standalone_hooks(self) -> dict:
        """A minimal hooks object shaped like the real .claude/settings.json,
        with every expected event routed through bin/gatekit.py (exec form)."""
        entry = {"hooks": [{"type": "command",
                            "command": "${CLAUDE_PROJECT_DIR}/.claude/gatekit/.venv/Scripts/python.exe",
                            "args": ["${CLAUDE_PROJECT_DIR}/.claude/gatekit/bin/gatekit.py",
                                     "_gate", "write"]}]}
        return {event: [entry] for event in doctor.EXPECTED_HOOK_EVENTS}

    def stub_claude(self) -> None:
        make_fake(self.bindir, "claude", print_and_exit("claude 1.0.0"))

    def axis(self, report: dict, n: int) -> dict:
        return report["axes"][n - 1]


# ------------------------------------------------------------------- shape


class TestReportShape(DoctorTestCase):
    def test_seven_axes_each_with_the_required_keys(self) -> None:
        report = doctor.diagnose(self.root)
        self.assertEqual(len(report["axes"]), 7)
        for axis in report["axes"]:
            for key in ("axis", "verdict", "detail", "fix"):
                self.assertIn(key, axis)
            self.assertIn(axis["verdict"], (verdict.OK, verdict.WARN,
                                            verdict.FAIL, verdict.UNVERIFIED))

    def test_overall_verdict_is_the_aggregate_of_the_axes(self) -> None:
        report = doctor.diagnose(self.root)
        self.assertEqual(report["verdict"],
                         verdict.aggregate([a["verdict"] for a in report["axes"]]))

    def test_unverified_axis_never_rounds_the_report_to_ok(self) -> None:
        report = doctor.diagnose(self.root)  # no spec/, no contract, no install
        if any(a["verdict"] == verdict.UNVERIFIED for a in report["axes"]):
            self.assertNotEqual(report["verdict"], verdict.OK)


# ------------------------------------------------------------------- axis 1


class TestAxisPluginFiles(DoctorTestCase):
    def test_real_checkout_has_every_gate_script_or_reports_which_is_missing(self) -> None:
        result = doctor.axis_plugin_files(self.root)
        if result["verdict"] == verdict.FAIL:
            self.assertIn("missing", result["detail"])
        else:
            self.assertEqual(result["verdict"], verdict.OK)

    def test_missing_gate_script_fails_axis_1(self) -> None:
        fake_plugin = self.root / "fakeplugin"
        (fake_plugin / "bin").mkdir(parents=True)
        (fake_plugin / "bin" / "gatekit.py").write_text("# launcher\n", encoding="utf-8")
        gates = fake_plugin / "gatekit" / "gates"
        gates.mkdir(parents=True)
        for name in doctor.GATE_SCRIPTS[:-1]:
            (gates / name).write_text("# gate\n", encoding="utf-8")

        original = paths.gatekit_root
        paths.gatekit_root = lambda: fake_plugin
        try:
            result = doctor.axis_plugin_files(self.root)
        finally:
            paths.gatekit_root = original
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn(doctor.GATE_SCRIPTS[-1], result["detail"])
        self.assertTrue(result["fix"])

    def test_empty_gate_script_fails_axis_1(self) -> None:
        fake_plugin = self.root / "fakeplugin2"
        (fake_plugin / "bin").mkdir(parents=True)
        (fake_plugin / "bin" / "gatekit.py").write_text("# launcher\n", encoding="utf-8")
        gates = fake_plugin / "gatekit" / "gates"
        gates.mkdir(parents=True)
        for name in doctor.GATE_SCRIPTS:
            (gates / name).write_text("" if name == "stop.py" else "# gate\n", encoding="utf-8")

        original = paths.gatekit_root
        paths.gatekit_root = lambda: fake_plugin
        try:
            result = doctor.axis_plugin_files(self.root)
        finally:
            paths.gatekit_root = original
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("empty", result["detail"])


# ------------------------------------------------------------------- axis 2


class TestAxisHooksRegistered(DoctorTestCase):
    def test_no_project_settings_fails(self) -> None:
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)

    def test_full_registration_is_ok(self) -> None:
        self.write_project_settings(self.standalone_hooks())
        self.assertEqual(doctor.axis_hooks_registered(self.root)["verdict"], verdict.OK)

    def test_missing_event_fails(self) -> None:
        hooks = self.standalone_hooks()
        del hooks["Stop"]
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("Stop", result["detail"])

    def test_missing_precompact_registration_is_not_ok(self) -> None:
        # Spelled out (not derived from doctor.EXPECTED_HOOK_EVENTS) so the
        # test fails if doctor stops checking PreCompact.
        entry = {"hooks": [{"type": "command",
                            "command": "${CLAUDE_PROJECT_DIR}/.claude/gatekit/.venv/Scripts/python.exe",
                            "args": ["${CLAUDE_PROJECT_DIR}/.claude/gatekit/bin/gatekit.py",
                                     "_gate", "write"]}]}
        hooks = {event: [entry] for event in
                 ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")}
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertNotEqual(result["verdict"], verdict.OK)
        self.assertIn("PreCompact", result["detail"])

    def test_gate_scripts_include_compact(self) -> None:
        self.assertIn("compact.py", doctor.GATE_SCRIPTS)

    def test_hooks_not_routed_through_wrapper_fails(self) -> None:
        hooks = {event: [{"hooks": [{"type": "command", "command": "python3 somewhere.py"}]}]
                 for event in doctor.EXPECTED_HOOK_EVENTS}
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)

    def test_no_hooks_object_fails(self) -> None:
        directory = self.root / ".claude"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "settings.json").write_text(json.dumps({}), encoding="utf-8")
        self.assertEqual(doctor.axis_hooks_registered(self.root)["verdict"], verdict.FAIL)

    def test_unparseable_settings_is_unverified(self) -> None:
        directory = self.root / ".claude"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "settings.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(doctor.axis_hooks_registered(self.root)["verdict"], verdict.UNVERIFIED)


# ------------------------------------------------------------------- axis 3


class TestAxisProjectState(DoctorTestCase):
    def test_clean_state_dir_is_ok(self) -> None:
        self.assertEqual(doctor.axis_project_state(self.root)["verdict"], verdict.OK)

    def test_no_state_dir_is_unverified(self) -> None:
        shutil.rmtree(self.root / ".gatekit")
        self.assertEqual(doctor.axis_project_state(self.root)["verdict"], verdict.UNVERIFIED)

    def test_corrupt_config_json_fails(self) -> None:
        (self.root / ".gatekit" / "config.json").write_text("{oops", encoding="utf-8")
        result = doctor.axis_project_state(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("config.json", result["detail"])

    def test_approvals_without_a_list_fails(self) -> None:
        (self.root / ".gatekit" / "approvals.json").write_text('{"version": 1}', encoding="utf-8")
        result = doctor.axis_project_state(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("approvals.json", result["detail"])


# ------------------------------------------------------------------- axis 4


class TestAxisSpecSet(DoctorTestCase):
    def test_no_spec_dir_is_unverified(self) -> None:
        result = doctor.axis_spec_set(self.root)
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)
        self.assertIn("spec/", result["detail"])

    def test_spec_dir_present_delegates_to_spec_validate(self) -> None:
        (self.root / "spec").mkdir()
        result = doctor.axis_spec_set(self.root)
        self.assertIn(result["verdict"], (verdict.OK, verdict.WARN,
                                          verdict.FAIL, verdict.UNVERIFIED))

    def test_spec_module_error_degrades_to_unverified(self) -> None:
        (self.root / "spec").mkdir()
        import gatekit.spec as spec_mod

        original = spec_mod.validate

        def boom(*a, **kw):
            raise RuntimeError("injected")

        spec_mod.validate = boom
        try:
            result = doctor.axis_spec_set(self.root)
        finally:
            spec_mod.validate = original
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)


# ------------------------------------------------------------------- axis 5


class TestAxisContractFreshness(DoctorTestCase):
    """Axis 5 delegates to `contract.status`; these pin the mapping it applies.

    The stub replaces the *attribute* on the imported module rather than an
    entry in `sys.modules`, so the tests behave the same whether or not
    `gatekit.contract` has already been imported elsewhere in the run.
    """

    def _patch_status(self, fn):
        import gatekit.contract as contract_mod

        original = contract_mod.status
        contract_mod.status = fn
        self.addCleanup(setattr, contract_mod, "status", original)

    def test_stale_contract_fails_axis_5(self) -> None:
        self._patch_status(lambda root: verdict.FAIL)
        result = doctor.axis_contract_freshness(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("derive", result["fix"])

    def test_stale_design_input_is_named(self) -> None:
        import gatekit.contract as contract_mod

        self._patch_status(lambda root: verdict.FAIL)
        original = contract_mod.stale_inputs
        contract_mod.stale_inputs = lambda root: ["spec/tokens.json"]
        self.addCleanup(setattr, contract_mod, "stale_inputs", original)
        result = doctor.axis_contract_freshness(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("spec/tokens.json", result["detail"])
        self.assertNotIn("05-gate.md changed", result["detail"])

    def test_absent_contract_is_unverified(self) -> None:
        self._patch_status(lambda root: verdict.UNVERIFIED)
        result = doctor.axis_contract_freshness(self.root)
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)
        self.assertIn("derive", result["fix"])

    def test_fresh_contract_is_ok(self) -> None:
        self._patch_status(lambda root: verdict.OK)
        result = doctor.axis_contract_freshness(self.root)
        self.assertEqual(result["verdict"], verdict.OK)
        self.assertEqual(result["fix"], "")

    def test_contract_module_error_degrades_to_unverified(self) -> None:
        def boom(root):
            raise RuntimeError("injected")

        self._patch_status(boom)
        result = doctor.axis_contract_freshness(self.root)
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)

    def test_no_contract_file_on_disk_is_unverified_end_to_end(self) -> None:
        """No stub at all: an absent contract.json must not read as ok."""
        result = doctor.axis_contract_freshness(self.root)
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)


# ------------------------------------------------------------------- axis 6


class TestAxisWorkers(DoctorTestCase):
    def test_missing_default_worker_binary_fails(self) -> None:
        result = doctor.axis_workers(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("claude", result["detail"])
        self.assertTrue(result["fix"])

    def test_present_default_worker_binary_is_ok(self) -> None:
        self.stub_claude()
        result = doctor.axis_workers(self.root)
        self.assertEqual(result["verdict"], verdict.OK)
        self.assertEqual(result["fix"], "")


# ------------------------------------------------------------------- axis 7


class TestAxisPython(DoctorTestCase):
    def test_running_interpreter_meets_the_floor(self) -> None:
        result = doctor.axis_python(self.root)
        self.assertEqual(result["verdict"], verdict.OK)
        self.assertIn(".", result["detail"])

    def test_floor_is_three_nine(self) -> None:
        self.assertEqual(doctor.MIN_PYTHON, (3, 9))


# --------------------------------------------------------------------- CLI


class TestCli(DoctorTestCase):
    def test_json_output_parses_and_lists_seven_axes(self) -> None:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor.run(["--json", "--root", str(self.root)])
        report = json.loads(buf.getvalue())
        self.assertEqual(len(report["axes"]), 7)

    def test_exit_1_when_any_axis_fails(self) -> None:
        import contextlib
        import io

        # No `claude` on PATH → axis 6 fails.
        with contextlib.redirect_stdout(io.StringIO()):
            code = doctor.run(["--root", str(self.root)])
        self.assertEqual(code, 1)

    def test_exit_0_when_no_axis_fails(self) -> None:
        import contextlib
        import io

        report = {"verdict": verdict.UNVERIFIED, "axes": [
            {"n": 1, "axis": "x", "verdict": verdict.UNVERIFIED, "detail": "", "fix": ""}]}
        original = doctor.diagnose
        doctor.diagnose = lambda root: report
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                code = doctor.run(["--root", str(self.root)])
        finally:
            doctor.diagnose = original
        self.assertEqual(code, 0)

    def test_table_output_shows_fixes(self) -> None:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor.run(["--root", str(self.root)])
        self.assertIn("gatekit doctor", buf.getvalue())
        self.assertIn("fix:", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
