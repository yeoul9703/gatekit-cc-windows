"""Tests for gates/prompt.py — ledger bootstrap, language detection, context."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import hookio, ledger  # noqa: E402
from gatekit.gates import prompt as prompt_gate  # noqa: E402
from tests import isolation  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "prompt.py"


class PromptProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        self.session = "sess-prompt"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def event(self, prompt_text: str, session: str = "") -> dict:
        return {
            "session_id": session or self.session,
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(self.root),
            "prompt": prompt_text,
        }

    def led(self, session: str = "") -> ledger.Ledger:
        return ledger.Ledger.load(self.root, session or self.session)

    def context_of(self, result) -> str:
        return result["hookSpecificOutput"]["additionalContext"]


class TestLedgerBootstrap(PromptProject):
    def test_creates_ledger_file(self) -> None:
        prompt_gate.handle(self.event("hello"))
        self.assertTrue(ledger.Ledger.exists(self.root, self.session))

    def test_never_blocks(self) -> None:
        """UserPromptSubmit has no deny path; output is context or nothing."""
        result = prompt_gate.handle(self.event("hello"))
        if result is not None:
            self.assertNotIn("permissionDecision", json.dumps(result))
            self.assertNotIn("decision", result)

    def test_records_prompt_event(self) -> None:
        prompt_gate.handle(self.event("hello"))
        kinds = [e["kind"] for e in self.led().data["events"]]
        self.assertIn("prompt", kinds)

    def test_separate_sessions_have_separate_ledgers(self) -> None:
        prompt_gate.handle(self.event("/gatekit-build", session="s-one"))
        prompt_gate.handle(self.event("hello there", session="s-two"))
        self.assertEqual(self.led("s-one").data["active_pipeline"], "build")
        self.assertIsNone(self.led("s-two").data["active_pipeline"])


class TestLanguageIsKorean(PromptProject):
    """The output language is Korean whatever the prompt is written in."""

    def test_korean_prompt_stores_ko(self) -> None:
        prompt_gate.handle(self.event("로그인 화면을 만들어줘"))
        self.assertEqual(self.led().data["output_lang"], "ko")

    def test_english_prompt_stores_ko(self) -> None:
        prompt_gate.handle(self.event("build the login screen"))
        self.assertEqual(self.led().data["output_lang"], "ko")

    def test_an_english_prompt_after_a_korean_one_stays_ko(self) -> None:
        prompt_gate.handle(self.event("로그인 화면을 만들어줘"))
        for reply in ("now switch to english please", "option 2 please", "", "1", "2."):
            prompt_gate.handle(self.event(reply))
            self.assertEqual(self.led().data["output_lang"], "ko", reply)

    def test_a_ledger_stored_as_english_is_rewritten(self) -> None:
        """A session an earlier version stored as English turns Korean on its next prompt."""
        led = self.led()
        led.set_output_lang("en")
        led.save()
        self.assertEqual(self.led().output_lang, "en")
        prompt_gate.handle(self.event("keep going in english"))
        self.assertEqual(self.led().data["output_lang"], "ko")

    def test_context_reports_the_language(self) -> None:
        result = prompt_gate.handle(self.event("hello"))
        self.assertIn("output_lang=ko", self.context_of(result))


class TestContextPayload(PromptProject):
    def test_shape_is_user_prompt_submit(self) -> None:
        result = prompt_gate.handle(self.event("hello"))
        block = result["hookSpecificOutput"]
        self.assertEqual(block["hookEventName"], "UserPromptSubmit")
        self.assertIn("additionalContext", block)

    def test_context_within_600_chars(self) -> None:
        led = self.led()
        led.data["active_pipeline"] = "build"
        led.data["questions"]["asked"] = 7
        led.save()
        result = prompt_gate.handle(self.event("x" * 3000))
        self.assertLessEqual(len(self.context_of(result)), hookio.MAX_CONTEXT_CHARS)

    def test_context_mentions_pipeline(self) -> None:
        led = self.led()
        led.data["active_pipeline"] = "build"
        led.save()
        self.assertIn("build", self.context_of(prompt_gate.handle(self.event("go"))))

    def test_context_mentions_question_budget(self) -> None:
        led = self.led()
        led.data["questions"]["asked"] = 2
        led.data["questions"]["max_calls"] = 2
        led.save()
        context = self.context_of(prompt_gate.handle(self.event("go")))
        self.assertIn("2", context)

    def test_context_reports_unresolved_gate_count(self) -> None:
        (self.root / "spec").mkdir()
        (self.root / "spec" / "05-gate.md").write_text("# Gate\n", encoding="utf-8")
        context = self.context_of(prompt_gate.handle(self.event("go")))
        self.assertTrue(context)


class TestSubprocess(PromptProject):
    def _run(self, event: dict) -> "tuple[int, str, str]":
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = isolation.run_gate(
            [sys.executable, str(GATE_SCRIPT)],
            cwd=self.root,
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_allow_with_context_via_subprocess(self) -> None:
        code, out, err = self._run(self.event("hello"))
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(
            payload["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit"
        )

    def test_english_prompt_stores_ko_via_subprocess(self) -> None:
        code, out, err = self._run(self.event("build the login screen"))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.led().data["output_lang"], "ko")
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("output_lang=ko", context)

    def test_internal_error_exits_zero_and_logs(self) -> None:
        runs = self.root / ".gatekit" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / f"{self.session}.json").mkdir()
        code, _, err = self._run(self.event("hello"))
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)
        self.assertTrue((runs / "hook-errors.log").is_file())

    def test_empty_stdin_exits_zero(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        # No event means no cwd: the gate takes the project of its working directory,
        # and in a managed project it records the prompt under "unknown-session".
        proc = isolation.run_gate(
            [sys.executable, str(GATE_SCRIPT)],
            cwd=self.root,
            input="",
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(ledger.Ledger.exists(self.root, "unknown-session"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestPipelineDetection(PromptProject):
    """The prompt gate, not the command prose, records which pipeline is active.
    Nothing else in production sets ``active_pipeline``; without this the stop
    gate and the question budget never engage."""

    @staticmethod
    def tagged(name: str, args: str = "") -> str:
        """The tagged prompt body Claude Code sends for a slash invocation."""
        return (
            "<command-message>gatekit-%s</command-message>\n"
            "<command-name>/gatekit-%s</command-name>\n"
            "<command-args>%s</command-args>" % (name, name, args)
        )

    def test_tagged_slash_command_sets_pipeline(self) -> None:
        prompt_gate.handle(self.event(self.tagged("build")))
        self.assertEqual(self.led().data["active_pipeline"], "build")

    def test_tagged_command_with_args(self) -> None:
        prompt_gate.handle(self.event(self.tagged("interview", "a todo app")))
        self.assertEqual(self.led().data["active_pipeline"], "interview")

    def test_tagged_doctor_clears(self) -> None:
        prompt_gate.handle(self.event(self.tagged("build")))
        prompt_gate.handle(self.event(self.tagged("doctor")))
        self.assertIsNone(self.led().data["active_pipeline"])

    def test_slash_command_sets_pipeline(self) -> None:
        prompt_gate.handle(self.event("/gatekit-build"))
        self.assertEqual(self.led().data["active_pipeline"], "build")

    def test_slash_command_with_arguments(self) -> None:
        prompt_gate.handle(self.event("  /gatekit-interview a todo app in Korean"))
        self.assertEqual(self.led().data["active_pipeline"], "interview")

    def test_expanded_command_heading_sets_pipeline(self) -> None:
        body = "---\nname: verify\n---\n\n# /gatekit-verify\n\nInput: ..."
        prompt_gate.handle(self.event(body))
        self.assertEqual(self.led().data["active_pipeline"], "verify")

    def test_plain_prompt_keeps_pipeline(self) -> None:
        prompt_gate.handle(self.event("/gatekit-build"))
        prompt_gate.handle(self.event("why did task auth-token fail?"))
        self.assertEqual(self.led().data["active_pipeline"], "build")

    def test_mention_mid_sentence_does_not_switch(self) -> None:
        prompt_gate.handle(self.event("/gatekit-build"))
        prompt_gate.handle(self.event("later I will run /gatekit-verify, not now"))
        self.assertEqual(self.led().data["active_pipeline"], "build")

    def test_non_pipeline_command_clears(self) -> None:
        prompt_gate.handle(self.event("/gatekit-build"))
        prompt_gate.handle(self.event("/gatekit-doctor"))
        self.assertIsNone(self.led().data["active_pipeline"])

    def test_unknown_gatekit_command_leaves_pipeline(self) -> None:
        prompt_gate.handle(self.event("/gatekit-build"))
        prompt_gate.handle(self.event("/gatekit-nonsense"))
        self.assertEqual(self.led().data["active_pipeline"], "build")

    def test_pipeline_change_resets_question_budget(self) -> None:
        prompt_gate.handle(self.event("/gatekit-interview x"))
        led = self.led()
        led.data["questions"]["asked"] = 3
        led.data["questions"]["budget_exceeded"] = True
        led.save()
        prompt_gate.handle(self.event("/gatekit-tasks"))
        questions = self.led().data["questions"]
        self.assertEqual(questions["asked"], 0)
        self.assertFalse(questions["budget_exceeded"])

    def test_same_pipeline_again_does_not_reset(self) -> None:
        prompt_gate.handle(self.event("/gatekit-interview x"))
        led = self.led()
        led.data["questions"]["asked"] = 1
        led.save()
        prompt_gate.handle(self.event("/gatekit-interview y"))
        self.assertEqual(self.led().data["questions"]["asked"], 1)

    def test_context_names_detected_pipeline(self) -> None:
        result = prompt_gate.handle(self.event("/gatekit-build"))
        self.assertIn("pipeline=build", self.context_of(result))

    def test_old_colon_form_is_not_an_invocation(self) -> None:
        prompt_gate.handle(self.event("/gatekit" + ":build"))
        prompt_gate.handle(self.event(
            "<command-name>/gatekit" + ":build</command-name>\n<command-args></command-args>"))
        self.assertIsNone(self.led().data.get("active_pipeline"))

    def test_a_longer_name_is_not_its_prefix(self) -> None:
        for text in ("/gatekit-build-state", "/gatekit-build_x"):
            self.assertIsNone(prompt_gate.detect_command(text), text)
        self.assertEqual(prompt_gate.detect_command("/gatekit-builder"), "builder")

    def test_every_known_command_name_is_extracted(self) -> None:
        for name in tuple(ledger.PIPELINES) + prompt_gate.NON_PIPELINE_COMMANDS:
            tagged = "<command-name>/gatekit-%s</command-name>" % name
            for text in ("/gatekit-" + name, "/gatekit-%s some args" % name,
                         "# /gatekit-" + name, tagged):
                self.assertEqual(prompt_gate.detect_command(text), name, text)

    def test_records_pipeline_event(self) -> None:
        prompt_gate.handle(self.event("/gatekit-gate"))
        events = [e for e in self.led().data["events"] if e["kind"] == "pipeline_set"]
        self.assertEqual(events[-1]["detail"]["pipeline"], "gate")


class TestDiscoverPipeline(PromptProject):
    def test_discover_command_sets_pipeline(self) -> None:
        prompt_gate.handle(self.event(
            "<command-message>gatekit-discover</command-message>\n"
            "<command-name>/gatekit-discover</command-name>\n"
            "<command-args></command-args>"))
        self.assertEqual(self.led().data["active_pipeline"], "discover")


class TestLanguageFromSlashCommand(PromptProject):
    """A slash command arrives as a tagged body of Latin letters. Neither the
    tags nor English arguments turn the session to English."""

    def tagged(self, name: str, args: str) -> str:
        return (
            "<command-message>gatekit-%s</command-message>\n"
            "<command-name>/gatekit-%s</command-name>\n"
            "<command-args>%s</command-args>" % (name, name, args)
        )

    def test_empty_args_keeps_korean(self) -> None:
        prompt_gate.handle(self.event("동네 러닝크루 출석 앱을 만들고 싶어요"))
        prompt_gate.handle(self.event(self.tagged("discover", "")))
        self.assertEqual(self.led().output_lang, "ko")

    def test_short_korean_args_stay_korean(self) -> None:
        prompt_gate.handle(self.event(self.tagged("interview", "출석 앱")))
        self.assertEqual(self.led().output_lang, "ko")

    def test_english_args_stay_korean(self) -> None:
        prompt_gate.handle(self.event(self.tagged("interview", "an attendance app for my running crew")))
        self.assertEqual(self.led().output_lang, "ko")
        self.assertEqual(self.led().data["active_pipeline"], "interview")


class TestQuestionFlagsInContext(unittest.TestCase):
    """ADR-0012 decision 5: the signals that mean something ride along."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        self.led = ledger.Ledger.load(self.root, "sess-flags")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def context_with(self, **fields) -> str:
        self.led.data["questions"] = dict({"asked": 6, "max_calls": 2}, **fields)
        return prompt_gate.build_context(self.root, self.led)

    def test_a_clean_session_prints_only_the_count(self) -> None:
        self.assertIn("questions=6/2 |", self.context_with())

    def test_unjustified_is_reported(self) -> None:
        self.assertIn("questions=6/2 (2 unjustified)", self.context_with(unjustified=2))

    def test_several_flags_are_joined(self) -> None:
        text = self.context_with(unjustified=2, repeated=1)
        self.assertIn("2 unjustified", text)
        self.assertIn("1 repeat", text)

    def test_implementation_choice_is_named(self) -> None:
        self.assertIn("impl-choice", self.context_with(implementation_choice=True))

    def test_a_malformed_count_does_not_break_the_line(self) -> None:
        self.assertIn("questions=6/2", self.context_with(unjustified="lots"))

    def test_the_block_stays_within_the_budget(self) -> None:
        text = self.context_with(unjustified=9, repeated=9, unrealized=9,
                                 implementation_choice=True)
        self.assertLessEqual(len(text), hookio.MAX_CONTEXT_CHARS)


class TestBuildStateInContext(unittest.TestCase):
    """ADR-0013 decision 1a: the session that comes back after a compaction is
    told a build is live, so it reads PROGRESS.md instead of guessing."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        self.led = ledger.Ledger.load(self.root, "sess-build")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def make_job(self, states: dict, finished: bool = False) -> str:
        from gatekit import jobs
        job_id = jobs.new_job_id()
        jdir = jobs.job_dir(self.root, job_id)
        (jdir / "tasks").mkdir(parents=True)
        job = {"version": 1, "job_id": job_id, "started_at": jobs._now(),
               "execution": "host", "tasks": list(states), "backend": {"name": "claude"}}
        if finished:
            job["finished_at"] = jobs._now()
        jobs.write_json(jdir / "job.json", job)
        for task_id, state in states.items():
            tdir = jdir / "tasks" / task_id
            tdir.mkdir(parents=True)
            jobs.write_json(tdir / "status.json", {"task_id": task_id, "state": state})
        return job_id

    def test_a_live_build_is_named(self) -> None:
        self.make_job({"a": "passed", "b": "queued"})
        text = prompt_gate.build_context(self.root, self.led)
        self.assertIn("build=", text)
        self.assertIn("1/2", text)

    def test_the_next_task_is_named(self) -> None:
        self.make_job({"a": "passed", "b": "queued"})
        self.assertIn("next: b", prompt_gate.build_context(self.root, self.led))

    def test_a_finished_build_is_not_reported(self) -> None:
        self.make_job({"a": "passed"}, finished=True)
        self.assertNotIn("build=", prompt_gate.build_context(self.root, self.led))

    def test_no_job_means_no_field(self) -> None:
        self.assertNotIn("build=", prompt_gate.build_context(self.root, self.led))

    def test_the_block_stays_within_budget(self) -> None:
        self.make_job({("task-with-a-long-name-%02d" % i): "queued" for i in range(30)})
        text = prompt_gate.build_context(self.root, self.led)
        self.assertLessEqual(len(text), hookio.MAX_CONTEXT_CHARS)


class TestUnmanagedProject(unittest.TestCase):
    """A project with no `.gatekit/` never asked gatekit to govern it.

    The plugin installs globally, so this hook fires everywhere. It must
    inject no context and leave no state behind in unrelated work.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".git").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_context_is_injected(self) -> None:
        event = {"session_id": "u", "cwd": str(self.root),
                 "hook_event_name": "UserPromptSubmit", "prompt": "안녕 도와줘"}
        self.assertIsNone(prompt_gate.handle(event))

    def test_no_state_is_created(self) -> None:
        event = {"session_id": "u", "cwd": str(self.root),
                 "hook_event_name": "UserPromptSubmit", "prompt": "hello"}
        prompt_gate.handle(event)
        self.assertFalse((self.root / ".gatekit").exists())
