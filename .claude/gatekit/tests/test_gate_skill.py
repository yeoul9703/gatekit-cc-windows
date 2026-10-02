"""Tests for gates/skill.py — a model-started skill records its pipeline."""
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
from gatekit.gates import prompt as prompt_gate  # noqa: E402
from gatekit.gates import skill as skill_gate  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "skill.py"


class SkillProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        self.session = "sess-skill"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def event(self, skill, tool: str = "Skill") -> dict:
        return {
            "session_id": self.session,
            "hook_event_name": "PreToolUse",
            "cwd": str(self.root),
            "tool_name": tool,
            "tool_input": {"skill": skill},
        }

    def led(self) -> ledger.Ledger:
        return ledger.Ledger.load(self.root, self.session)

    def pipeline(self):
        return self.led().data["active_pipeline"]

    def run_skill(self, skill, **kwargs) -> None:
        """Call the hook and assert the one thing true of every call: it allows."""
        self.assertIsNone(skill_gate.handle(self.event(skill, **kwargs)))


class TestMeasuredHookInput(SkillProject):
    """The payload recorded by the probe of 2026-10-02 (ADR-0021), with the
    skill renamed to a gatekit one and ``cwd`` pointed at this test's project."""

    def measured(self, skill: str) -> dict:
        return {
            "session_id": "86738f70-9e46-4d32-a97f-f93d3f23e994",
            "transcript_path": str(self.root / "transcript.jsonl"),
            "cwd": str(self.root),
            "prompt_id": "7573cc93-4f26-4197-8316-1d82d151d35a",
            "permission_mode": "default",
            "effort": {"level": "medium"},
            "hook_event_name": "PreToolUse",
            "tool_name": "Skill",
            "tool_input": {"skill": skill},
            "tool_use_id": "toolu_01XShEyTsANKNiDJDNR99kwX",
        }

    def test_model_started_skill_sets_the_pipeline(self) -> None:
        self.assertIsNone(skill_gate.handle(self.measured("gatekit-build")))
        led = ledger.Ledger.load(self.root, "86738f70-9e46-4d32-a97f-f93d3f23e994")
        self.assertEqual(led.data["active_pipeline"], "build")

    def test_the_probe_skill_itself_is_ignored(self) -> None:
        self.assertIsNone(skill_gate.handle(self.measured("gkx-build")))
        self.assertFalse(ledger.Ledger.exists(self.root, "86738f70-9e46-4d32-a97f-f93d3f23e994"))

    def test_natural_language_prompt_then_skill_call(self) -> None:
        """The case the prompt gate cannot see: the prompt names no skill."""
        session = "86738f70-9e46-4d32-a97f-f93d3f23e994"
        prompt_gate.handle({"session_id": session, "cwd": str(self.root),
                            "hook_event_name": "UserPromptSubmit",
                            "prompt": "please run the gatekit build"})
        self.assertIsNone(ledger.Ledger.load(self.root, session).data["active_pipeline"])
        skill_gate.handle(self.measured("gatekit-build"))
        self.assertEqual(ledger.Ledger.load(self.root, session).data["active_pipeline"], "build")


class TestPipelineSkills(SkillProject):
    def test_every_pipeline_skill_sets_its_pipeline(self) -> None:
        for name in ledger.PIPELINES:
            self.run_skill("gatekit-" + name)
            self.assertEqual(self.pipeline(), name)

    def test_pipeline_change_resets_question_budget(self) -> None:
        self.run_skill("gatekit-interview")
        led = self.led()
        led.data["questions"]["asked"] = 3
        led.data["questions"]["budget_exceeded"] = True
        led.save()
        self.run_skill("gatekit-tasks")
        questions = self.led().data["questions"]
        self.assertEqual(questions["asked"], 0)
        self.assertFalse(questions["budget_exceeded"])

    def test_same_pipeline_again_does_not_reset(self) -> None:
        self.run_skill("gatekit-interview")
        led = self.led()
        led.data["questions"]["asked"] = 1
        led.save()
        self.run_skill("gatekit-interview")
        self.assertEqual(self.led().data["questions"]["asked"], 1)

    def test_records_events(self) -> None:
        self.run_skill("gatekit-gate")
        events = self.led().data["events"]
        self.assertEqual([e["kind"] for e in events], ["pipeline_set", "skill"])
        self.assertEqual(events[0]["detail"]["pipeline"], "gate")
        self.assertEqual(events[1]["detail"], {"skill": "gate"})

    def test_keeps_the_stored_language(self) -> None:
        led = self.led()
        led.set_output_lang("ko")
        led.save()
        self.run_skill("gatekit-build")
        self.assertEqual(self.led().output_lang, "ko")

    def test_leading_slash_is_accepted(self) -> None:
        self.run_skill("/gatekit-verify")
        self.assertEqual(self.pipeline(), "verify")

    def test_same_result_as_the_slash_command_in_a_prompt(self) -> None:
        for name in tuple(ledger.PIPELINES) + prompt_gate.NON_PIPELINE_COMMANDS:
            self.assertEqual(prompt_gate.skill_command("gatekit-" + name),
                             prompt_gate.detect_command("/gatekit-" + name), name)


class TestNonPipelineSkills(SkillProject):
    def test_doctor_and_setup_clear_the_pipeline(self) -> None:
        for name in ("doctor", "setup"):
            self.run_skill("gatekit-build")
            self.assertEqual(self.pipeline(), "build")
            self.run_skill("gatekit-" + name)
            self.assertIsNone(self.pipeline(), name)

    def test_the_list_is_the_prompt_gate_list(self) -> None:
        self.assertEqual(prompt_gate.NON_PIPELINE_COMMANDS, ("doctor", "setup"))


class TestIgnoredSkills(SkillProject):
    def test_non_gatekit_skills_leave_the_pipeline_and_the_ledger(self) -> None:
        self.run_skill("gatekit-build")
        before = self.led().data["events"]
        for skill in ("code-review", "anthropic-skills:docs", "skill-creator:skill-creator",
                      "gkx-build", "build", "gatekit", "gatekit-", "other:gatekit-verify",
                      "gatekit-build-state", "gatekit-build_x", "gatekit-Build",
                      "gatekit:verify", "my-gatekit-verify", "gatekit-verify extra"):
            self.run_skill(skill)
            self.assertEqual(self.pipeline(), "build", skill)
        self.assertEqual(self.led().data["events"], before)

    def test_unknown_gatekit_name_leaves_the_pipeline(self) -> None:
        self.run_skill("gatekit-build")
        for skill in ("gatekit-nonsense", "gatekit-shared", "gatekit-builder"):
            self.run_skill(skill)
            self.assertEqual(self.pipeline(), "build", skill)

    def test_non_gatekit_skill_creates_no_ledger(self) -> None:
        self.run_skill("code-review")
        self.run_skill("gatekit-nonsense")
        self.assertFalse(ledger.Ledger.exists(self.root, self.session))

    def test_other_tools_are_ignored(self) -> None:
        self.run_skill("gatekit-build", tool="Bash")
        self.run_skill("gatekit-build", tool="Agent")
        self.assertFalse(ledger.Ledger.exists(self.root, self.session))


class TestMalformedInput(SkillProject):
    def test_bad_tool_input_shapes_are_ignored(self) -> None:
        for tool_input in (None, "gatekit-build", ["gatekit-build"], 7, {}, {"skill": None},
                           {"skill": 7}, {"skill": ["gatekit-build"]}, {"skill": ""},
                           {"skill": {"name": "gatekit-build"}}, {"name": "gatekit-build"}):
            event = self.event("x")
            event["tool_input"] = tool_input
            self.assertIsNone(skill_gate.handle(event), tool_input)
        self.assertFalse(ledger.Ledger.exists(self.root, self.session))

    def test_missing_keys_are_ignored(self) -> None:
        self.assertIsNone(skill_gate.handle({}))
        self.assertIsNone(skill_gate.handle({"tool_name": "Skill"}))
        self.assertIsNone(skill_gate.handle({"tool_name": "Skill", "cwd": str(self.root),
                                             "tool_input": {"skill": "gatekit-build"}}))

    def test_extra_tool_input_keys_are_ignored(self) -> None:
        event = self.event("gatekit-build")
        event["tool_input"]["args"] = "anything at all"
        self.assertIsNone(skill_gate.handle(event))
        self.assertEqual(self.pipeline(), "build")


class TestNeverBlocks(SkillProject):
    def test_no_input_produces_a_payload(self) -> None:
        """This hook records; it has no deny path at all."""
        for skill in ("gatekit-build", "gatekit-doctor", "gatekit-nonsense", "code-review", "", 7):
            self.assertIsNone(skill_gate.handle(self.event(skill)), skill)

    def test_does_not_block_while_writes_are_restricted(self) -> None:
        (self.root / "spec").mkdir()
        (self.root / "spec" / "05-gate.md").write_text("# Gate\n", encoding="utf-8")
        os.environ["GATEKIT_TASK_ID"] = "auth"
        try:
            self.run_skill("gatekit-build")
        finally:
            del os.environ["GATEKIT_TASK_ID"]
        self.assertEqual(self.pipeline(), "build")


class TestUnmanagedProject(unittest.TestCase):
    """A project with no `.gatekit/` never asked gatekit to govern it."""

    def test_no_state_is_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(os.path.realpath(tmp))
            (root / ".git").mkdir()
            event = {"session_id": "u", "cwd": str(root), "hook_event_name": "PreToolUse",
                     "tool_name": "Skill", "tool_input": {"skill": "gatekit-build"}}
            self.assertIsNone(skill_gate.handle(event))
            self.assertFalse((root / ".gatekit").exists())


class TestSubprocess(SkillProject):
    def _run(self, event: "dict | None", raw: "str | None" = None, argv: "list | None" = None):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            argv or [sys.executable, str(GATE_SCRIPT)],
            input=raw if raw is not None else json.dumps(event),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_records_and_prints_nothing(self) -> None:
        code, out, err = self._run(self.event("gatekit-verify"))
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")
        self.assertEqual(self.pipeline(), "verify")

    def test_through_the_cli_dispatcher(self) -> None:
        launcher = pathlib.Path(__file__).resolve().parents[1] / "bin" / "gatekit.py"
        code, out, err = self._run(self.event("gatekit-build"),
                                   argv=[sys.executable, str(launcher), "_gate", "skill"])
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")
        self.assertEqual(self.pipeline(), "build")

    def test_bad_json_and_empty_stdin_exit_zero(self) -> None:
        for raw in ("this is not json", "", "[1, 2]"):
            code, out, err = self._run(None, raw=raw)
            self.assertEqual(code, 0, err)
            self.assertEqual(out.strip(), "")

    def test_internal_error_exits_zero_and_logs(self) -> None:
        runs = self.root / ".gatekit" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / f"{self.session}.json").mkdir()  # the ledger cannot be written
        code, out, err = self._run(self.event("gatekit-build"))
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")
        self.assertNotIn("Traceback", err)
        log = runs / "hook-errors.log"
        self.assertTrue(log.is_file())
        self.assertIn("PreToolUse", log.read_text(encoding="utf-8"))


class TestRegistration(unittest.TestCase):
    def test_settings_json_routes_skill_to_this_hook(self) -> None:
        # .claude/gatekit/tests/test_gate_skill.py -> parents[3] == repo root
        settings_path = pathlib.Path(__file__).resolve().parents[3] / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        matchers = {entry.get("matcher"): entry for entry in settings["hooks"]["PreToolUse"]}
        self.assertIn("Skill", matchers)
        self.assertEqual(len(matchers["Skill"]["hooks"]), 1)
        hook = matchers["Skill"]["hooks"][0]
        # exec form: no shell string, the gate name is the last argv element
        self.assertEqual(hook["type"], "command")
        self.assertTrue(hook["command"].endswith(".venv/Scripts/python.exe"))
        self.assertEqual(hook["args"][-2:], ["_gate", "skill"])
        self.assertTrue(hook["args"][0].endswith("bin/gatekit.py"))
        self.assertEqual(len(hook["args"]), 3)

    def test_cli_and_doctor_list_the_hook(self) -> None:
        from gatekit import cli, doctor

        self.assertIn("skill", cli.GATES)
        self.assertIn("skill.py", doctor.GATE_SCRIPTS)


if __name__ == "__main__":
    unittest.main()
