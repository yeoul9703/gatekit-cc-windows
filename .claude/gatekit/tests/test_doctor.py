"""Tests for gatekit.doctor — 8 axes, fault-injected one at a time.

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
from unittest import mock

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import doctor, paths, verdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fakebin import make_fake, print_and_exit  # noqa: E402


GATE_ENTRY = {"hooks": [{
    "type": "command",
    "command": "${CLAUDE_PROJECT_DIR}/.claude/gatekit/.venv/Scripts/python.exe",
    "args": ["${CLAUDE_PROJECT_DIR}/.claude/gatekit/bin/gatekit.py", "_gate", "write"]}]}


def gate_entry(gate, matcher=None) -> dict:
    """One hook group routed to ``_gate <gate>``, shaped like the real settings.json."""
    entry = {"hooks": [{
        "type": "command",
        "command": "${CLAUDE_PROJECT_DIR}/.claude/gatekit/.venv/Scripts/python.exe",
        "args": ["${CLAUDE_PROJECT_DIR}/.claude/gatekit/bin/gatekit.py", "_gate", gate]}]}
    if matcher is not None:
        entry["matcher"] = matcher
    return entry


SESSION_ENTRY = {"hooks": [{
    "type": "command", "command": "powershell.exe",
    "args": ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             "${CLAUDE_PROJECT_DIR}/.claude/gatekit/scripts/session-check.ps1"]}]}


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

    def write_project_settings(self, hooks, drop=()) -> None:
        """settings.json with *hooks* and the two PowerShell settings, minus the
        top-level keys named in *drop*."""
        directory = self.root / ".claude"
        directory.mkdir(parents=True, exist_ok=True)
        settings = {"env": {"CLAUDE_CODE_USE_POWERSHELL_TOOL": "1"},
                    "defaultShell": "powershell", "hooks": hooks}
        for key in drop:
            del settings[key]
        (directory / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    def standalone_hooks(self) -> dict:
        """A minimal hooks object shaped like the real .claude/settings.json,
        with every expected event routed through bin/gatekit.py (exec form)."""
        return {
            "SessionStart": [SESSION_ENTRY],
            "UserPromptSubmit": [gate_entry("prompt")],
            "PreToolUse": [
                gate_entry("write", "Write|Edit|MultiEdit|NotebookEdit"),
                gate_entry("bash", "Bash"),
                gate_entry("powershell", "PowerShell"),
                gate_entry("spawn", "Agent|Task"),
                gate_entry("skill", "Skill"),
            ],
            "PostToolUse": [
                gate_entry("question", "AskUserQuestion"),
                gate_entry("question", "Write|Edit|MultiEdit|NotebookEdit"),
                gate_entry("release", "Agent|Task"),
            ],
            "SubagentStop": [gate_entry("release")],
            "PreCompact": [gate_entry("compact")],
            "Stop": [gate_entry("stop")],
        }

    def write_config(self, data: dict) -> None:
        state = self.root / ".gatekit"
        state.mkdir(exist_ok=True)
        (state / "config.json").write_text(json.dumps(data), encoding="utf-8")

    def stub_claude(self) -> None:
        make_fake(self.bindir, "claude", print_and_exit("claude 1.0.0"))

    def axis(self, report: dict, n: int) -> dict:
        return report["axes"][n - 1]


# ------------------------------------------------------------------- shape


class TestReportShape(DoctorTestCase):
    def test_eight_axes_each_with_the_required_keys(self) -> None:
        report = doctor.diagnose(self.root)
        self.assertEqual(len(report["axes"]), 8)
        self.assertEqual([a["axis"] for a in report["axes"]][:2],
                         ["gatekit files", "hooks registered"])
        self.assertEqual(report["axes"][-1]["axis"], "uv")
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
    def make_full_tree(self, base, skip=None, empty=None) -> None:
        """A gatekit root holding every file axis 1 requires, minus *skip*."""
        wanted = list(doctor.PROJECT_FILES)
        wanted += ["gatekit/gates/" + n for n in doctor.GATE_SCRIPTS]
        wanted += ["scripts/" + n for n in doctor.POWERSHELL_SCRIPTS]
        for rel in wanted:
            if rel == skip:
                continue
            target = base.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("" if rel == empty else "# content\n", encoding="utf-8")

    def check_fake_tree(self, base) -> dict:
        original = paths.gatekit_root
        paths.gatekit_root = lambda: base
        try:
            return doctor.axis_gatekit_files(self.root)
        finally:
            paths.gatekit_root = original

    def test_complete_tree_is_ok_and_needs_no_sh_wrapper(self) -> None:
        base = self.root / "fullplugin"
        self.make_full_tree(base)
        self.assertFalse((base / "bin" / "gatekit").exists())
        self.assertEqual(self.check_fake_tree(base)["verdict"], verdict.OK)

    def test_each_required_non_gate_file_is_checked(self) -> None:
        expected = ["bin/gatekit.py", "pyproject.toml", "uv.lock", "scripts/session-check.ps1",
                    "scripts/setup.ps1", "scripts/verify.ps1"]
        for rel in expected:
            base = self.root / ("tree-" + rel.replace("/", "-"))
            self.make_full_tree(base, skip=rel)
            result = self.check_fake_tree(base)
            self.assertEqual(result["verdict"], verdict.FAIL, rel)
            self.assertIn(rel, result["detail"])

    def test_real_checkout_axis_1_is_ok(self) -> None:
        self.assertEqual(doctor.axis_gatekit_files(self.root)["verdict"], verdict.OK)

    def test_real_checkout_has_every_gate_script_or_reports_which_is_missing(self) -> None:
        result = doctor.axis_gatekit_files(self.root)
        if result["verdict"] == verdict.FAIL:
            self.assertIn("없거나 비어 있음", result["detail"])
        else:
            self.assertEqual(result["verdict"], verdict.OK)

    def test_missing_gate_script_fails_axis_1(self) -> None:
        fake_plugin = self.root / "fakeplugin"
        self.make_full_tree(fake_plugin, skip="gatekit/gates/" + doctor.GATE_SCRIPTS[-1])

        original = paths.gatekit_root
        paths.gatekit_root = lambda: fake_plugin
        try:
            result = doctor.axis_gatekit_files(self.root)
        finally:
            paths.gatekit_root = original
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn(doctor.GATE_SCRIPTS[-1], result["detail"])
        self.assertTrue(result["fix"])

    def test_empty_gate_script_fails_axis_1(self) -> None:
        fake_plugin = self.root / "fakeplugin2"
        self.make_full_tree(fake_plugin, empty="gatekit/gates/stop.py")

        original = paths.gatekit_root
        paths.gatekit_root = lambda: fake_plugin
        try:
            result = doctor.axis_gatekit_files(self.root)
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

    def test_missing_powershell_setting_fails_and_points_to_setup(self) -> None:
        for drop, named in (("env", "CLAUDE_CODE_USE_POWERSHELL_TOOL"), ("defaultShell", "defaultShell")):
            with self.subTest(drop=drop):
                self.write_project_settings(self.standalone_hooks(), drop=(drop,))
                result = doctor.axis_hooks_registered(self.root)
                self.assertEqual(result["verdict"], verdict.FAIL, result)
                self.assertIn(named, result["detail"])
                self.assertIn("/gatekit-setup", result["fix"])

    def test_wrong_powershell_setting_values_fail(self) -> None:
        directory = self.root / ".claude"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "settings.json").write_text(json.dumps({
            "env": {"CLAUDE_CODE_USE_POWERSHELL_TOOL": "0"}, "defaultShell": "bash",
            "hooks": self.standalone_hooks()}), encoding="utf-8")
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("CLAUDE_CODE_USE_POWERSHELL_TOOL", result["detail"])
        self.assertIn("defaultShell", result["detail"])

    def test_a_hook_problem_is_reported_before_the_powershell_settings(self) -> None:
        hooks = self.standalone_hooks()
        del hooks["Stop"]
        self.write_project_settings(hooks, drop=("env",))
        self.assertIn("Stop", doctor.axis_hooks_registered(self.root)["detail"])

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
        hooks = {event: [GATE_ENTRY] for event in
                 ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")}
        hooks["SessionStart"] = [SESSION_ENTRY]
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

    def test_missing_powershell_matcher_fails(self) -> None:
        hooks = self.standalone_hooks()
        hooks["PreToolUse"] = [g for g in hooks["PreToolUse"] if g["matcher"] != "PowerShell"]
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL, result)
        self.assertIn("PowerShell (_gate powershell)", result["detail"])
        self.assertNotIn("Skill", result["detail"])
        self.assertTrue(result["fix"])

    def test_missing_skill_matcher_fails(self) -> None:
        hooks = self.standalone_hooks()
        hooks["PreToolUse"] = [g for g in hooks["PreToolUse"] if g["matcher"] != "Skill"]
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL, result)
        self.assertIn("Skill (_gate skill)", result["detail"])
        self.assertNotIn("PowerShell", result["detail"])

    def test_both_missing_matchers_are_named(self) -> None:
        # Spelled out (not derived from doctor.REQUIRED_HOOKS) so the
        # test fails if doctor stops requiring either one.
        hooks = self.standalone_hooks()
        hooks["PreToolUse"] = [gate_entry("write", "Write|Edit|MultiEdit|NotebookEdit"),
                               gate_entry("bash", "Bash"), gate_entry("spawn", "Agent|Task")]
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("PowerShell", result["detail"])
        self.assertIn("Skill", result["detail"])

    # -- every gatekit hook is required (ADR-0022) -----------------------
    def test_each_required_hook_fails_alone_and_is_named(self) -> None:
        # Spelled out, not derived from doctor.REQUIRED_HOOKS: the test fails if
        # doctor stops requiring one of them.
        wanted = (
            ("UserPromptSubmit", None, "prompt", "UserPromptSubmit (_gate prompt)"),
            ("PreToolUse", "Write|Edit|MultiEdit|NotebookEdit", "write",
             "PreToolUse Write (_gate write)"),
            ("PreToolUse", "Bash", "bash", "PreToolUse Bash (_gate bash)"),
            ("PreToolUse", "PowerShell", "powershell", "PreToolUse PowerShell (_gate powershell)"),
            ("PreToolUse", "Agent|Task", "spawn", "PreToolUse Agent (_gate spawn)"),
            ("PreToolUse", "Skill", "skill", "PreToolUse Skill (_gate skill)"),
            ("PostToolUse", "AskUserQuestion", "question",
             "PostToolUse AskUserQuestion (_gate question)"),
            ("PostToolUse", "Write|Edit|MultiEdit|NotebookEdit", "question",
             "PostToolUse NotebookEdit (_gate question)"),
            ("PostToolUse", "Agent|Task", "release", "PostToolUse Task (_gate release)"),
            ("SubagentStop", None, "release", "SubagentStop (_gate release)"),
            ("PreCompact", None, "compact", "PreCompact (_gate compact)"),
            ("Stop", None, "stop", "Stop (_gate stop)"),
        )
        self.assertEqual(len(wanted), len(doctor.REQUIRED_HOOKS))
        for event, matcher, gate, named in wanted:
            with self.subTest(event=event, matcher=matcher, gate=gate):
                hooks = self.standalone_hooks()
                # Reroute the one group to another gate: the event stays
                # registered, so only the required-hook check can catch it.
                for group in hooks[event]:
                    if group.get("matcher") == matcher and group["hooks"][0]["args"][-1] == gate:
                        group["hooks"][0]["args"][-1] = "tokens"
                self.write_project_settings(hooks)
                result = doctor.axis_hooks_registered(self.root)
                self.assertEqual(result["verdict"], verdict.FAIL, result)
                self.assertIn(named, result["detail"])
                self.assertIn("settings.json", result["fix"])

    def test_one_tool_missing_from_a_matcher_is_named_alone(self) -> None:
        hooks = self.standalone_hooks()
        hooks["PreToolUse"][0]["matcher"] = "Write|Edit|MultiEdit"
        hooks["PostToolUse"][2]["matcher"] = "Agent"
        self.write_project_settings(hooks)
        detail = doctor.axis_hooks_registered(self.root)["detail"]
        self.assertIn("PreToolUse NotebookEdit (_gate write)", detail)
        self.assertIn("PostToolUse Task (_gate release)", detail)
        self.assertNotIn("PreToolUse Write (", detail)
        self.assertNotIn("PostToolUse Agent (", detail)

    def test_missing_subagent_stop_fails(self) -> None:
        hooks = self.standalone_hooks()
        del hooks["SubagentStop"]
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("SubagentStop", result["detail"])

    def test_a_tool_may_be_covered_by_split_groups(self) -> None:
        hooks = self.standalone_hooks()
        hooks["PreToolUse"][3:4] = [gate_entry("spawn", "Agent"), gate_entry("spawn", "Task")]
        self.write_project_settings(hooks)
        self.assertEqual(doctor.axis_hooks_registered(self.root)["verdict"], verdict.OK)

    def test_a_gate_under_the_wrong_event_does_not_count(self) -> None:
        hooks = self.standalone_hooks()
        hooks["PostToolUse"] = hooks["PostToolUse"][:2]
        hooks["PreToolUse"].append(gate_entry("release", "Agent|Task"))
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("PostToolUse Agent (_gate release)", result["detail"])

    def test_required_hooks_are_exactly_the_real_settings_json(self) -> None:
        """Both directions: a hook added to settings.json without a row in
        REQUIRED_HOOKS fails here, and so does a row with no registration."""
        project = pathlib.Path(__file__).resolve().parents[3]
        settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
        registered = set()
        for event, groups in settings["hooks"].items():
            for group in groups:
                for hook in group["hooks"]:
                    args = hook.get("args") or []
                    if len(args) >= 2 and args[-2] == "_gate":
                        matcher = group.get("matcher")
                        for tool in (matcher.split("|") if matcher else [None]):
                            registered.add((event, tool, args[-1]))
        required = set()
        for event, matcher, gate in doctor.REQUIRED_HOOKS:
            for tool in (matcher.split("|") if matcher else [None]):
                required.add((event, tool, gate))
        self.assertEqual(sorted(registered - required, key=str), [], "registered, not required")
        self.assertEqual(sorted(required - registered, key=str), [], "required, not registered")
        self.assertEqual(len(doctor.REQUIRED_HOOKS), len(set(doctor.REQUIRED_HOOKS)))

    def test_required_hook_events_and_gates_are_known(self) -> None:
        from gatekit import cli

        for event, _matcher, gate in doctor.REQUIRED_HOOKS:
            self.assertIn(event, doctor.EXPECTED_HOOK_EVENTS)
            self.assertIn(gate, cli.GATES)
            self.assertIn(gate + ".py", doctor.GATE_SCRIPTS)

    def test_bash_matcher_does_not_stand_in_for_powershell(self) -> None:
        hooks = self.standalone_hooks()
        hooks["PreToolUse"][2] = gate_entry("powershell", "Bash")
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("PowerShell", result["detail"])

    def test_matcher_routed_to_the_wrong_gate_fails(self) -> None:
        hooks = self.standalone_hooks()
        hooks["PreToolUse"][2] = gate_entry("bash", "PowerShell")
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("PowerShell (_gate powershell)", result["detail"])

    def test_alternation_and_catch_all_matchers_cover_the_tool(self) -> None:
        for matcher in ("Bash|PowerShell", "*", None):
            with self.subTest(matcher=matcher):
                hooks = self.standalone_hooks()
                hooks["PreToolUse"][2] = gate_entry("powershell", matcher)
                self.write_project_settings(hooks)
                self.assertEqual(doctor.axis_hooks_registered(self.root)["verdict"], verdict.OK)

    def test_gate_scripts_include_powershell_and_skill(self) -> None:
        self.assertIn("powershell.py", doctor.GATE_SCRIPTS)
        self.assertIn("skill.py", doctor.GATE_SCRIPTS)

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
        self.assertIn("계약이 낡았습니다", result["detail"])
        self.assertNotIn("05-gate.md", result["detail"])  # the file that changed is named, not the gate

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
    """The CLI is needed only in a project whose settings start it (doctor.cli_required)."""

    def test_missing_default_worker_binary_fails_when_build_runs_workers(self) -> None:
        self.write_config({"build": {"execution": "worker"}})
        result = doctor.axis_workers(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("claude", result["detail"])
        self.assertTrue(result["fix"])

    def test_missing_default_worker_binary_fails_when_a_backend_is_the_evaluator(self) -> None:
        self.write_config({"verify": {"evaluator": "claude"}})
        result = doctor.axis_workers(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertTrue(result["fix"])

    def test_missing_default_worker_binary_is_ok_with_the_default_settings(self) -> None:
        for data in (None, {"build": {"execution": "host"}}, {"verify": {"evaluator": "agent"}}):
            with self.subTest(config=data):
                if data is not None:
                    self.write_config(data)
                result = doctor.axis_workers(self.root)
                self.assertEqual(result["verdict"], verdict.OK)
                self.assertIn("기본 워커 claude: PATH 에서 찾지 못함", result["detail"])
                self.assertIn("지금 설정(build.execution=host)에서는 쓰지 않는다", result["detail"])
                self.assertEqual(result["fix"], "")

    def test_cli_required_reads_the_two_settings(self) -> None:
        self.assertFalse(doctor.cli_required(self.root))  # no config file
        cases = (({}, False), ({"build": {"execution": "host"}}, False),
                 ({"build": {"execution": "worker"}}, True),
                 ({"build": {"execution": "Worker"}}, False),  # a typo means host (jobs.execution_mode)
                 ({"verify": {"evaluator": ""}}, False), ({"verify": {"evaluator": "agent"}}, False),
                 ({"verify": {"evaluator": "claude"}}, True),
                 ({"verify": {"evaluator": "no-such-backend"}}, True),  # as written, like common.ps1
                 ({"verify": {"evaluator": 3}}, False))
        for data, expected in cases:
            with self.subTest(config=data):
                self.write_config(data)
                self.assertEqual(doctor.cli_required(self.root), expected)
        (self.root / ".gatekit" / "config.json").write_text("{not json", encoding="utf-8")
        self.assertFalse(doctor.cli_required(self.root))

    def test_present_default_worker_binary_is_ok(self) -> None:
        self.stub_claude()
        result = doctor.axis_workers(self.root)
        self.assertEqual(result["verdict"], verdict.OK)
        self.assertEqual(result["fix"], "")


# ------------------------------------------------------------------- axis 7


class TestAxisPython(DoctorTestCase):
    """Axis 7 checks the project venv's interpreter, not the running one."""

    def venv_tree(self, cfg_text, with_python=True):
        kit = self.root / "kit"
        (kit / ".venv" / "Scripts").mkdir(parents=True)
        if with_python:
            (kit / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
        if cfg_text is not None:
            (kit / ".venv" / "pyvenv.cfg").write_text(cfg_text, encoding="utf-8")
        return kit

    def run_axis(self, kit) -> dict:
        original = paths.gatekit_root
        paths.gatekit_root = lambda: kit
        try:
            return doctor.axis_python(self.root)
        finally:
            paths.gatekit_root = original

    def test_floor_is_three_fourteen(self) -> None:
        self.assertEqual(doctor.MIN_PYTHON, (3, 14))

    def test_floor_comes_from_packages_json(self) -> None:
        kit = self.venv_tree("version_info = 3.14.3\n")
        (kit / "scripts").mkdir()
        (kit / "scripts" / "packages.json").write_text('{"python_min": "3.99"}', encoding="utf-8")
        result = self.run_axis(kit)
        self.assertEqual(result["verdict"], verdict.FAIL, result)
        self.assertIn("3.99", result["detail"])

    def test_unreadable_python_min_falls_back_to_three_fourteen(self) -> None:
        bad = self.root / "packages.json"
        bad.write_text('{"python_min": "latest"}', encoding="utf-8")
        self.assertEqual(doctor.min_python(bad), (3, 14))
        self.assertEqual(doctor.min_python(self.root / "missing.json"), (3, 14))

    def test_real_venv_meets_the_floor(self) -> None:
        result = doctor.axis_python(self.root)
        self.assertEqual(result["verdict"], verdict.OK, result)
        self.assertRegex(result["detail"], r"^\.venv 파이썬 3\.\d+\.\d+$")

    def test_missing_venv_fails_and_says_hooks_are_inactive(self) -> None:
        kit = self.root / "kit"
        kit.mkdir()
        result = self.run_axis(kit)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("python.exe 가 없어 gatekit 훅이 모두 조용히 꺼져 있습니다", result["detail"])
        self.assertIn("/gatekit-setup", result["fix"])

    def test_uv_style_cfg_at_the_floor_is_ok(self) -> None:
        kit = self.venv_tree("home = x\nversion_info = 3.14.0\n")
        result = self.run_axis(kit)
        self.assertEqual(result["verdict"], verdict.OK)
        self.assertIn("3.14.0", result["detail"])

    def test_stdlib_style_cfg_is_read_too(self) -> None:
        kit = self.venv_tree("version = 3.14.3\n")
        self.assertEqual(self.run_axis(kit)["verdict"], verdict.OK)

    def test_old_venv_python_fails(self) -> None:
        for old in ("3.10.14", "3.11.9", "3.13.5"):
            kit = self.venv_tree("version_info = %s\n" % old)
            result = self.run_axis(kit)
            self.assertEqual(result["verdict"], verdict.FAIL, old)
            self.assertIn(old, result["detail"])
            self.assertIn("-Install venv", result["fix"])
            shutil.rmtree(kit)

    def test_unreadable_version_is_unverified_not_ok(self) -> None:
        kit = self.venv_tree("home = x\n")
        self.assertEqual(self.run_axis(kit)["verdict"], verdict.UNVERIFIED)


class TestAxisUv(DoctorTestCase):
    def test_uv_missing_fails_with_install_hint(self) -> None:
        result = doctor.axis_uv(self.root)  # PATH holds only an empty scratch dir
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("winget install --id=astral-sh.uv -e", result["fix"])

    def test_uv_present_reports_its_version(self) -> None:
        make_fake(self.bindir, "uv", print_and_exit("uv 9.9.9 (fake)"))
        result = doctor.axis_uv(self.root)
        self.assertEqual(result["verdict"], verdict.OK)
        self.assertIn("uv 9.9.9", result["detail"])

    def test_uv_that_does_not_answer_is_unverified(self) -> None:
        make_fake(self.bindir, "uv", print_and_exit("", exit_code=1))
        self.assertEqual(doctor.axis_uv(self.root)["verdict"], verdict.UNVERIFIED)

    def test_uv_is_the_last_axis(self) -> None:
        self.assertIs(doctor.AXES[-1], doctor.axis_uv)


class TestHooksExecForm(DoctorTestCase):
    def test_shell_string_hook_is_not_ok(self) -> None:
        hooks = self.standalone_hooks()
        hooks["Stop"] = [{"hooks": [{
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR/.claude/gatekit/bin/gatekit\" _gate stop"}]}]
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("exec 형식", result["detail"])
        self.assertTrue(result["detail"].endswith("아닌 훅: Stop"), result["detail"])

    def test_missing_session_start_fails(self) -> None:
        hooks = self.standalone_hooks()
        del hooks["SessionStart"]
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("SessionStart", result["detail"])

    def test_session_start_must_run_the_check_script(self) -> None:
        hooks = self.standalone_hooks()
        hooks["SessionStart"] = [GATE_ENTRY]
        self.write_project_settings(hooks)
        result = doctor.axis_hooks_registered(self.root)
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("SessionStart", result["detail"])

    def _session_hook_args(self, args) -> dict:
        hooks = self.standalone_hooks()
        hooks["SessionStart"] = [{"hooks": [{
            "type": "command", "command": "powershell.exe", "args": args}]}]
        self.write_project_settings(hooks)
        return doctor.axis_hooks_registered(self.root)

    def test_powershell_hook_without_noprofile_fails(self) -> None:
        result = self._session_hook_args(
            ["-ExecutionPolicy", "Bypass", "-File", "x/scripts/session-check.ps1"])
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("-NoProfile", result["detail"])
        self.assertIn("SessionStart", result["detail"])

    def test_powershell_hook_without_bypass_fails(self) -> None:
        for args in (["-NoProfile", "-File", "x/scripts/session-check.ps1"],
                     ["-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-File",
                      "x/scripts/session-check.ps1"]):
            result = self._session_hook_args(args)
            self.assertEqual(result["verdict"], verdict.FAIL, args)
            self.assertIn("-ExecutionPolicy Bypass", result["detail"])

    def test_powershell_hook_with_both_flags_is_ok(self) -> None:
        result = self._session_hook_args(
            ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "x/scripts/session-check.ps1"])
        self.assertEqual(result["verdict"], verdict.OK)

    def test_the_required_arguments_are_what_the_check_reads_and_prints(self) -> None:
        # REQUIRED_PS_ARGS is the one list: the check looks for these, the message names these.
        self.assertEqual(doctor.REQUIRED_PS_ARGS, ("-NoProfile", "-ExecutionPolicy", "Bypass"))
        usual = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "x/scripts/session-check.ps1"]
        with mock.patch.object(doctor, "REQUIRED_PS_ARGS", ("-NoLogo", "-ExecutionPolicy", "AllSigned")):
            result = self._session_hook_args(usual)
            self.assertEqual(result["verdict"], verdict.FAIL)
            self.assertIn("-NoLogo -ExecutionPolicy AllSigned", result["detail"])
            other = ["-nologo", "-executionpolicy", "allsigned", "-File", "x/scripts/session-check.ps1"]
            self.assertEqual(self._session_hook_args(other)["verdict"], verdict.OK)

    def test_real_settings_json_is_ok(self) -> None:
        project = pathlib.Path(__file__).resolve().parents[3]
        self.assertEqual(doctor.axis_hooks_registered(project)["verdict"], verdict.OK)


# --------------------------------------------------------------------- CLI


class TestCli(DoctorTestCase):
    def test_json_output_parses_and_lists_eight_axes(self) -> None:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor.run(["--json", "--root", str(self.root)])
        report = json.loads(buf.getvalue())
        self.assertEqual(len(report["axes"]), 8)

    def test_exit_1_when_any_axis_fails(self) -> None:
        import contextlib
        import io

        # A project that runs workers, and no `claude` on PATH → axis 6 fails.
        self.write_config({"build": {"execution": "worker"}})
        report = doctor.diagnose(self.root)
        self.assertEqual(self.axis(report, 6)["verdict"], verdict.FAIL)
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

    def _output(self, *argv) -> tuple:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = doctor.run([*argv, "--root", str(self.root)])
        return code, buf.getvalue()

    def test_default_output_is_korean_and_keeps_json_axis_keys(self) -> None:
        _, text = self._output()
        self.assertIn("gatekit 닥터", text)
        self.assertIn("설치 파일", text)
        self.assertIn("이 프로젝트에 spec/ 폴더가 없습니다", text)
        self.assertIn("해결:", text)
        self.assertNotIn("fix:", text)
        self.assertNotIn("gatekit doctor", text)
        self.assertNotIn("no spec/ directory in this project", text)
        _, raw = self._output("--json")
        axes = [a["axis"] for a in json.loads(raw)["axes"]]
        self.assertEqual(axes[:2], ["gatekit files", "hooks registered"])  # stable keys

    def test_lang_ko_is_the_default(self) -> None:
        self.assertEqual(self._output("--lang", "ko")[1], self._output()[1])

    def test_lang_en_is_still_accepted(self) -> None:
        """scripts/setup.ps1 still passes ``--lang en`` when it is run with ``-Lang en``:
        the argument is no error and the table it asks for is the English one."""
        code, text = self._output("--lang", "en")
        self.assertEqual(code, self._output()[0])
        self.assertIn("gatekit doctor", text)
        self.assertIn("fix:", text)
        self.assertIn("no spec/ directory in this project", text)
        self.assertNotIn("닥터", text)

    def test_unknown_lang_is_refused(self) -> None:
        import contextlib
        import io

        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self._output("--lang", "fr")[0], 2)

    def test_lang_does_not_leak_into_later_calls(self) -> None:
        self._output("--lang", "en")
        self.assertEqual(doctor._LANG, "ko")

    def test_table_output_shows_fixes(self) -> None:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            doctor.run(["--root", str(self.root)])
        self.assertIn("gatekit 닥터", buf.getvalue())
        self.assertIn("해결:", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
