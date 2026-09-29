"""Tests for gates/question.py — the AskUserQuestion budget counter."""
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
from gatekit.gates import question as question_gate  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "question.py"


class QuestionProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        self.session = "sess-q"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def event(self) -> dict:
        return {
            "session_id": self.session,
            "hook_event_name": "PostToolUse",
            "cwd": str(self.root),
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "which stack?"}]},
            "tool_response": {},
        }

    def led(self) -> ledger.Ledger:
        return ledger.Ledger.load(self.root, self.session)

    def set_pipeline(self, name, max_calls=None) -> None:
        led = self.led()
        led.data["active_pipeline"] = name
        if max_calls is not None:
            led.data["questions"]["max_calls"] = max_calls
        led.save()


class TestCounting(QuestionProject):
    def test_increments_asked(self) -> None:
        question_gate.handle(self.event())
        self.assertEqual(self.led().data["questions"]["asked"], 1)

    def test_increments_cumulatively(self) -> None:
        for _ in range(3):
            question_gate.handle(self.event())
        self.assertEqual(self.led().data["questions"]["asked"], 3)

    def test_returns_none_never_blocks(self) -> None:
        """PostToolUse has no block path; this gate is informational only."""
        for _ in range(5):
            self.assertIsNone(question_gate.handle(self.event()))

    def test_records_event(self) -> None:
        question_gate.handle(self.event())
        kinds = [e["kind"] for e in self.led().data["events"]]
        self.assertIn("question_asked", kinds)


class TestBudget(QuestionProject):
    def test_within_budget_is_not_exceeded(self) -> None:
        self.set_pipeline("interview", max_calls=2)
        question_gate.handle(self.event())
        question_gate.handle(self.event())
        self.assertFalse(self.led().data["questions"]["budget_exceeded"])

    def test_over_budget_sets_flag(self) -> None:
        self.set_pipeline("interview", max_calls=2)
        for _ in range(3):
            question_gate.handle(self.event())
        data = self.led().data["questions"]
        self.assertEqual(data["asked"], 3)
        self.assertTrue(data["budget_exceeded"])

    def test_flag_is_informational_not_a_block(self) -> None:
        self.set_pipeline("interview", max_calls=1)
        question_gate.handle(self.event())
        self.assertIsNone(question_gate.handle(self.event()))
        self.assertTrue(self.led().data["questions"]["budget_exceeded"])

    def test_non_interview_pipeline_is_unlimited(self) -> None:
        self.set_pipeline("build")
        for _ in range(20):
            question_gate.handle(self.event())
        self.assertFalse(self.led().data["questions"]["budget_exceeded"])

    def test_no_pipeline_is_unlimited(self) -> None:
        for _ in range(20):
            question_gate.handle(self.event())
        self.assertFalse(self.led().data["questions"]["budget_exceeded"])

    def test_interview_budget_default_is_two(self) -> None:
        self.set_pipeline("interview")
        for _ in range(3):
            question_gate.handle(self.event())
        self.assertTrue(self.led().data["questions"]["budget_exceeded"])

    def test_config_can_raise_the_interview_budget(self) -> None:
        (self.root / ".gatekit" / "config.json").write_text(
            json.dumps({"questions": {"interview_max_calls": 5}}), encoding="utf-8"
        )
        led = self.led()
        led.data["active_pipeline"] = "interview"
        led.save()
        for _ in range(4):
            question_gate.handle(self.event())
        self.assertFalse(self.led().data["questions"]["budget_exceeded"])


class TestSubprocess(QuestionProject):
    def _run(self, event: dict) -> "tuple[int, str, str]":
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_counts_via_subprocess(self) -> None:
        code, out, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")
        self.assertEqual(self.led().data["questions"]["asked"], 1)

    def test_over_budget_via_subprocess_still_exits_zero(self) -> None:
        self.set_pipeline("interview", max_calls=1)
        self._run(self.event())
        code, out, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")
        self.assertTrue(self.led().data["questions"]["budget_exceeded"])

    def test_internal_error_exits_zero_and_logs(self) -> None:
        runs = self.root / ".gatekit" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / f"{self.session}.json").mkdir()
        code, _, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)
        self.assertTrue((runs / "hook-errors.log").is_file())

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


# ------------------------------------------- ADR-0012: justify, don't just count


class ADR0012Project(QuestionProject):
    """Shared helpers for the justification, repeat and shape checks."""

    def ask(self, *questions, **kw) -> dict:
        """One AskUserQuestion event carrying *questions* (dicts or strings)."""
        payload = []
        for q in questions:
            payload.append({"question": q, "header": kw.get("header", "")}
                           if isinstance(q, str) else q)
        event = self.event()
        event["tool_input"] = {"questions": payload}
        return event

    def justify(self, line) -> None:
        led = self.led()
        led.data.setdefault("questions", {})["justification"] = line
        led.save()

    def spend_budget(self) -> None:
        """Use up the two free interview calls."""
        self.set_pipeline("interview")
        for _ in range(2):
            question_gate.handle(self.ask("free one"))


class TestJustification(ADR0012Project):
    def test_within_budget_needs_no_justification(self) -> None:
        self.set_pipeline("interview")
        question_gate.handle(self.ask("first"))
        question_gate.handle(self.ask("second"))
        self.assertEqual(self.led().data["questions"].get("unjustified", 0), 0)

    def test_over_budget_without_a_line_is_unjustified(self) -> None:
        self.spend_budget()
        question_gate.handle(self.ask("third"))
        self.assertEqual(self.led().data["questions"]["unjustified"], 1)

    def test_a_justified_over_budget_call_is_not_counted(self) -> None:
        self.spend_budget()
        self.justify("picks the injection shape")
        question_gate.handle(self.ask("third"))
        self.assertEqual(self.led().data["questions"].get("unjustified", 0), 0)

    def test_the_line_is_consumed_by_the_call_it_justifies(self) -> None:
        self.spend_budget()
        self.justify("picks the injection shape")
        question_gate.handle(self.ask("third"))
        question_gate.handle(self.ask("fourth"))
        self.assertEqual(self.led().data["questions"]["unjustified"], 1)
        self.assertIsNone(self.led().data["questions"].get("justification"))

    def test_a_blank_line_does_not_justify(self) -> None:
        self.spend_budget()
        self.justify("   ")
        question_gate.handle(self.ask("third"))
        self.assertEqual(self.led().data["questions"]["unjustified"], 1)

    def test_a_non_string_line_does_not_justify(self) -> None:
        self.spend_budget()
        self.justify({"why": "reasons"})
        question_gate.handle(self.ask("third"))
        self.assertEqual(self.led().data["questions"]["unjustified"], 1)

    def test_unbudgeted_pipeline_never_needs_a_line(self) -> None:
        self.set_pipeline("design")
        for _ in range(5):
            question_gate.handle(self.ask("anything"))
        self.assertEqual(self.led().data["questions"].get("unjustified", 0), 0)

    def test_budget_exceeded_keeps_its_meaning(self) -> None:
        self.spend_budget()
        self.justify("a good reason")
        question_gate.handle(self.ask("third"))
        self.assertTrue(self.led().data["questions"]["budget_exceeded"])


class TestRepeatedTopic(ADR0012Project):
    def test_the_same_question_twice_is_flagged(self) -> None:
        self.set_pipeline("interview")
        question_gate.handle(self.ask("when should we commit this work?"))
        question_gate.handle(self.ask("when should we commit this work?"))
        self.assertEqual(self.led().data["questions"]["repeated"], 1)

    def test_a_reworded_same_topic_is_flagged(self) -> None:
        self.set_pipeline("interview")
        question_gate.handle(self.ask("when should we commit the changes?"))
        question_gate.handle(self.ask("the changes: when should we commit?"))
        self.assertEqual(self.led().data["questions"]["repeated"], 1)

    def test_a_different_topic_is_not_flagged(self) -> None:
        self.set_pipeline("interview")
        question_gate.handle(self.ask("when should we commit the changes?"))
        question_gate.handle(self.ask("which database engine suits this workload?"))
        self.assertEqual(self.led().data["questions"].get("repeated", 0), 0)

    def test_a_merely_similar_topic_is_not_flagged(self) -> None:
        self.set_pipeline("interview")
        question_gate.handle(self.ask("should we commit the parser changes now?"))
        question_gate.handle(self.ask("should we deploy the finished game to vercel?"))
        self.assertEqual(self.led().data["questions"].get("repeated", 0), 0)

    def test_the_flag_names_the_earlier_call(self) -> None:
        self.set_pipeline("interview")
        question_gate.handle(self.ask("when should we commit this work?"))
        question_gate.handle(self.ask("unrelated matter entirely about colours"))
        question_gate.handle(self.ask("when should we commit this work?"))
        self.assertEqual(self.led().data["questions"]["repeat_of"], 1)

    def test_short_questions_do_not_collide(self) -> None:
        self.set_pipeline("interview")
        question_gate.handle(self.ask("ok?"))
        question_gate.handle(self.ask("no?"))
        self.assertEqual(self.led().data["questions"].get("repeated", 0), 0)


class TestImplementationChoice(ADR0012Project):
    def options(self, *labels) -> dict:
        return {"question": "which approach?", "header": "approach",
                "options": [{"label": l, "description": l} for l in labels]}

    def test_all_code_token_options_warn(self) -> None:
        self.set_pipeline("interview")
        question_gate.handle(self.ask(self.options(
            "inject into build_prompt()", "attach spec/design/preview.html",
            "check with gates/tokens.py")))
        self.assertTrue(self.led().data["questions"]["implementation_choice"])

    def test_priority_options_do_not_warn(self) -> None:
        self.set_pipeline("interview")
        question_gate.handle(self.ask(self.options(
            "speed matters most to us", "keeping the records matters most",
            "being able to play offline matters most")))
        self.assertFalse(self.led().data["questions"].get("implementation_choice"))

    def test_a_question_with_no_options_does_not_warn(self) -> None:
        self.set_pipeline("interview")
        question_gate.handle(self.ask("what did you try last time?"))
        self.assertFalse(self.led().data["questions"].get("implementation_choice"))

    def test_the_warning_is_not_a_block(self) -> None:
        self.set_pipeline("interview")
        out = question_gate.handle(self.ask(self.options(
            "run jobs.py", "run spec.py", "run design.py")))
        self.assertIsNone((out or {}).get("decision"))


class TestUnrealized(ADR0012Project):
    """Decision 3: a justification that produced no writing is recorded."""

    def write_event(self) -> dict:
        return {
            "session_id": self.session,
            "hook_event_name": "PostToolUse",
            "cwd": str(self.root),
            "tool_name": "Write",
            "tool_input": {"file_path": "x.py"},
        }

    def test_no_write_after_a_justified_question_is_unrealized(self) -> None:
        self.spend_budget()
        self.justify("changes the injection shape")
        question_gate.handle(self.ask("third"))
        question_gate.handle(self.ask("fourth"))
        self.assertEqual(self.led().data["questions"]["unrealized"], 1)

    def test_a_write_in_between_clears_it(self) -> None:
        self.spend_budget()
        self.justify("changes the injection shape")
        question_gate.handle(self.ask("third"))
        question_gate.note_write(self.root, self.session)
        question_gate.handle(self.ask("fourth"))
        self.assertEqual(self.led().data["questions"].get("unrealized", 0), 0)

    def test_an_unjustified_question_is_not_also_unrealized(self) -> None:
        self.spend_budget()
        question_gate.handle(self.ask("third"))
        question_gate.handle(self.ask("fourth"))
        self.assertEqual(self.led().data["questions"]["unjustified"], 2)
        self.assertEqual(self.led().data["questions"].get("unrealized", 0), 0)

    def test_a_write_event_does_not_count_as_a_question(self) -> None:
        self.set_pipeline("interview")
        question_gate.handle(self.ask("first"))
        question_gate.handle(self.write_event())
        self.assertEqual(self.led().data["questions"]["asked"], 1)

    def test_a_write_event_clears_the_watch_in_production_shape(self) -> None:
        self.spend_budget()
        self.justify("changes the injection shape")
        question_gate.handle(self.ask("third"))
        question_gate.handle(self.write_event())
        question_gate.handle(self.ask("fourth"))
        self.assertEqual(self.led().data["questions"].get("unrealized", 0), 0)

    def test_a_write_event_never_blocks(self) -> None:
        self.set_pipeline("interview")
        self.assertIsNone((question_gate.handle(self.write_event()) or {}).get("decision"))


class TestUnmanagedProject(unittest.TestCase):
    """No `.gatekit/` means no counting and no state left behind."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".git").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_question_leaves_no_state(self) -> None:
        event = {"session_id": "u", "cwd": str(self.root),
                 "hook_event_name": "PostToolUse",
                 "tool_name": "AskUserQuestion", "tool_input": {}}
        self.assertIsNone(question_gate.handle(event))
        self.assertFalse((self.root / ".gatekit").exists())

    def test_write_leaves_no_state(self) -> None:
        event = {"session_id": "u", "cwd": str(self.root),
                 "hook_event_name": "PostToolUse",
                 "tool_name": "Write", "tool_input": {"file_path": "a.txt"}}
        self.assertIsNone(question_gate.handle(event))
        self.assertFalse((self.root / ".gatekit").exists())
