"""Tests for gates/stop.py — contract-enforced completion."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import contract, ledger  # noqa: E402
from gatekit.gates import stop as stop_gate  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "stop.py"
PY = sys.executable


class StopProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        self.gate_md = self.root / "spec" / "05-gate.md"
        self.session = "sess-stop"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_contract(self, *criteria: dict) -> None:
        body = "# Gate\n\n" + "".join(
            "```gatekit-criterion\n" + json.dumps(c) + "\n```\n" for c in criteria
        )
        self.gate_md.write_text(body, encoding="utf-8")
        contract.derive(self.root)

    def passing(self) -> None:
        self.write_contract({"id": "ok-crit", "argv": [PY, "-c", "pass"], "timeout_s": 20})

    def failing(self) -> None:
        self.write_contract(
            {"id": "bad-crit", "argv": [PY, "-c", "raise SystemExit(1)"], "timeout_s": 20}
        )

    def set_pipeline(self, name: str) -> None:
        led = ledger.Ledger.load(self.root, self.session)
        led.data["active_pipeline"] = name
        led.save()

    def event(self, stop_hook_active: bool = False) -> dict:
        return {
            "session_id": self.session,
            "hook_event_name": "Stop",
            "cwd": str(self.root),
            "stop_hook_active": stop_hook_active,
        }

    def led(self) -> ledger.Ledger:
        return ledger.Ledger.load(self.root, self.session)


class TestBlocking(StopProject):
    def test_failing_contract_blocks_in_build(self) -> None:
        self.failing()
        self.set_pipeline("build")
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertEqual(result["decision"], "block")
        self.assertIn("bad-crit", result["reason"])

    def test_failing_contract_blocks_in_verify(self) -> None:
        self.failing()
        self.set_pipeline("verify")
        self.assertIsNotNone(stop_gate.handle(self.event()))

    def test_block_increments_count(self) -> None:
        self.failing()
        self.set_pipeline("build")
        stop_gate.handle(self.event())
        self.assertEqual(self.led().data["stop"]["block_count"], 1)

    def test_blocks_at_most_three_times(self) -> None:
        self.failing()
        self.set_pipeline("build")
        for _ in range(3):
            self.assertIsNotNone(stop_gate.handle(self.event()))
        # 4th attempt: block_count is now 3, so it must let the session stop.
        self.assertIsNone(stop_gate.handle(self.event()))

    def test_stop_hook_active_never_blocks(self) -> None:
        self.failing()
        self.set_pipeline("build")
        self.assertIsNone(stop_gate.handle(self.event(stop_hook_active=True)))

    def test_stop_hook_active_records_verdict(self) -> None:
        self.failing()
        self.set_pipeline("build")
        stop_gate.handle(self.event(stop_hook_active=True))
        self.assertIsNotNone(self.led().data["stop"]["final_verdict"])

    def test_unverified_also_blocks(self) -> None:
        self.write_contract(
            {"id": "slow", "argv": [PY, "-c", "import time; time.sleep(5)"], "timeout_s": 1}
        )
        self.set_pipeline("build")
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertIn("slow", result["reason"])

    def test_reason_lists_criterion_ids(self) -> None:
        self.write_contract(
            {"id": "alpha", "argv": [PY, "-c", "raise SystemExit(1)"], "timeout_s": 20},
            {"id": "beta", "argv": [PY, "-c", "raise SystemExit(1)"], "timeout_s": 20},
        )
        self.set_pipeline("build")
        reason = stop_gate.handle(self.event())["reason"]
        self.assertIn("alpha", reason)
        self.assertIn("beta", reason)

    def test_reasons_stored_in_ledger(self) -> None:
        self.failing()
        self.set_pipeline("build")
        stop_gate.handle(self.event())
        self.assertTrue(self.led().data["stop"]["last_reasons"])


class TestAllowing(StopProject):
    def test_passing_contract_allows(self) -> None:
        self.passing()
        self.set_pipeline("build")
        self.assertIsNone(stop_gate.handle(self.event()))

    def test_passing_records_ok_verdict(self) -> None:
        self.passing()
        self.set_pipeline("build")
        stop_gate.handle(self.event())
        self.assertEqual(self.led().data["stop"]["final_verdict"], "ok")

    def test_no_contract_allows(self) -> None:
        self.set_pipeline("build")
        self.assertIsNone(stop_gate.handle(self.event()))

    def test_inactive_pipeline_allows_without_running(self) -> None:
        self.failing()
        self.set_pipeline("interview")
        self.assertIsNone(stop_gate.handle(self.event()))

    def test_no_pipeline_allows(self) -> None:
        self.failing()
        self.assertIsNone(stop_gate.handle(self.event()))

    def test_final_verdict_is_never_blank_on_allow(self) -> None:
        self.passing()
        self.set_pipeline("build")
        stop_gate.handle(self.event())
        final = self.led().data["stop"]["final_verdict"]
        self.assertTrue(final)
        self.assertIn(final, ("ok", "warn", "fail", "unverified"))

    def test_verdict_recorded_when_giving_up_after_three_blocks(self) -> None:
        self.failing()
        self.set_pipeline("build")
        for _ in range(3):
            stop_gate.handle(self.event())
        stop_gate.handle(self.event())
        self.assertEqual(self.led().data["stop"]["final_verdict"], "fail")

    def test_stale_contract_blocks_with_stale_reason(self) -> None:
        self.passing()
        self.set_pipeline("build")
        self.gate_md.write_text(
            self.gate_md.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8"
        )
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertIn("contract_stale", result["reason"])


class TestLanguage(StopProject):
    def test_korean_reason(self) -> None:
        self.failing()
        led = self.led()
        led.data["active_pipeline"] = "build"
        led.set_output_lang("ko")
        led.save()
        reason = stop_gate.handle(self.event())["reason"]
        self.assertTrue(any("가" <= ch <= "힣" for ch in reason), reason)

    def test_english_reason_by_default(self) -> None:
        self.failing()
        self.set_pipeline("build")
        reason = stop_gate.handle(self.event())["reason"]
        self.assertFalse(any("가" <= ch <= "힣" for ch in reason), reason)


class TestSubprocess(StopProject):
    def _run(self, event: dict) -> "tuple[int, str, str]":
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_allow_via_subprocess(self) -> None:
        self.passing()
        self.set_pipeline("build")
        code, out, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")

    def test_block_via_subprocess_uses_top_level_decision(self) -> None:
        self.failing()
        self.set_pipeline("build")
        code, out, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("reason", payload)

    def test_internal_error_exits_zero_and_logs(self) -> None:
        self.failing()
        self.set_pipeline("build")
        runs = self.root / ".gatekit" / "runs"
        # Corrupt the ledger into a directory so every ledger write raises.
        target = runs / f"{self.session}.json"
        target.unlink()
        target.mkdir()
        code, _, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)
        self.assertTrue((runs / "hook-errors.log").is_file())

    def test_corrupt_contract_json_exits_zero(self) -> None:
        self.set_pipeline("build")
        (self.root / ".gatekit" / "contract.json").write_text("{broken", encoding="utf-8")
        code, out, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)

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


class TestHookTimeoutCoversBudget(unittest.TestCase):
    """The contract run inside the Stop hook must finish before Claude Code's
    hook timeout, or the gate is killed mid-run: no verdict, no log line."""

    def hook_timeout(self) -> float:
        # .claude/gatekit/tests/test_gate_stop.py -> parents[3] == repo root
        settings_path = pathlib.Path(__file__).resolve().parents[3] / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        return float(settings["hooks"]["Stop"][0]["hooks"][0]["timeout"])

    def test_settings_json_matches_declared_timeout(self) -> None:
        self.assertEqual(self.hook_timeout(), stop_gate.STOP_HOOK_TIMEOUT_S)

    def test_hook_timeout_is_the_documented_maximum(self) -> None:
        self.assertEqual(stop_gate.STOP_HOOK_TIMEOUT_S, 600.0)

    def test_cap_leaves_margin_below_hook_timeout(self) -> None:
        self.assertLessEqual(stop_gate.STOP_BUDGET_CAP_S + 30, stop_gate.STOP_HOOK_TIMEOUT_S)

    def test_cap_is_above_default_budget(self) -> None:
        self.assertGreater(stop_gate.STOP_BUDGET_CAP_S, contract.TOTAL_BUDGET_S)

    def test_no_dead_stop_budget_constant(self) -> None:
        self.assertFalse(hasattr(stop_gate, "STOP_BUDGET_S"))


class TestStopGateCapsDeclaredBudget(StopProject):
    def test_declared_budget_above_cap_is_capped(self) -> None:
        body = (
            "# Gate\n\n```gatekit-budget\n{\"total_budget_s\": 600}\n```\n"
            "```gatekit-criterion\n"
            + json.dumps({"id": "ok-crit", "argv": [PY, "-c", "pass"], "timeout_s": 20})
            + "\n```\n"
        )
        self.gate_md.write_text(body, encoding="utf-8")
        contract.derive(self.root)
        self.set_pipeline("build")
        seen = {}
        original = contract.execute

        def recorder(root, total_budget_s=None, cap_s=None):
            result = original(root, total_budget_s=total_budget_s, cap_s=cap_s)
            seen["budget"] = result["total_budget_s"]
            return result

        contract.execute = recorder
        try:
            stop_gate.handle(self.event())
        finally:
            contract.execute = original
        self.assertEqual(seen["budget"], stop_gate.STOP_BUDGET_CAP_S)

    def test_cli_run_is_not_capped(self) -> None:
        body = (
            "# Gate\n\n```gatekit-budget\n{\"total_budget_s\": 600}\n```\n"
            "```gatekit-criterion\n"
            + json.dumps({"id": "ok-crit", "argv": [PY, "-c", "pass"], "timeout_s": 20})
            + "\n```\n"
        )
        self.gate_md.write_text(body, encoding="utf-8")
        contract.derive(self.root)
        self.assertEqual(contract.execute(self.root)["total_budget_s"], 600.0)


class TestEndToEndViaPromptGate(StopProject):
    """No direct ledger injection: the prompt gate must be what arms the stop
    gate, exactly as it happens in a real session."""

    def prompt(self, text: str) -> None:
        from gatekit.gates import prompt as prompt_gate

        prompt_gate.handle(
            {
                "session_id": self.session,
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(self.root),
                "prompt": text,
            }
        )

    def test_build_command_then_failing_contract_blocks(self) -> None:
        self.failing()
        self.prompt(
            "<command-message>gatekit-build</command-message>\n"
            "<command-name>/gatekit-build</command-name>\n"
            "<command-args></command-args>"
        )
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertEqual(result["decision"], "block")

    def test_plain_chat_never_arms_stop_gate(self) -> None:
        self.failing()
        self.prompt("please build everything now")
        self.assertIsNone(stop_gate.handle(self.event()))
        self.assertEqual(self.led().data["stop"]["final_verdict"], "unverified")

    def test_doctor_after_build_disarms(self) -> None:
        self.failing()
        self.prompt("/gatekit-build")
        self.prompt("/gatekit-doctor")
        self.assertIsNone(stop_gate.handle(self.event()))


class TestReuse(StopProject):
    """ADR-0024: the stop gate does not run the contract again when nothing a
    criterion could see has changed since the last run."""

    def setUp(self) -> None:
        super().setUp()
        self.runs = 0
        self._original = contract.execute

        def counting(root, total_budget_s=None, cap_s=None):
            self.runs += 1
            return self._original(root, total_budget_s=total_budget_s, cap_s=cap_s)

        contract.execute = counting
        self.addCleanup(lambda: setattr(contract, "execute", self._original))
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")

    def cli_run(self) -> None:
        self.assertEqual(contract.run(["run", "--root", str(self.root)]), 0)

    def test_verify_then_stop_runs_the_contract_once(self) -> None:
        # contract run -> write spec/PROGRESS.md -> Stop: the answer is known.
        self.passing()
        self.set_pipeline("verify")
        self.cli_run()
        (self.root / "spec" / "PROGRESS.md").write_text("# progress\n", encoding="utf-8")
        self.assertIsNone(stop_gate.handle(self.event()))
        self.assertEqual(self.runs, 1)
        self.assertEqual(self.led().data["stop"]["final_verdict"], "ok")

    def test_a_turn_that_changes_nothing_reuses_the_gates_own_run(self) -> None:
        self.passing()
        self.set_pipeline("build")
        stop_gate.handle(self.event())
        stop_gate.handle(self.event())
        self.assertEqual(self.runs, 1)

    def test_a_failing_result_is_reused_and_still_blocks(self) -> None:
        self.failing()
        self.set_pipeline("build")
        first = stop_gate.handle(self.event())
        second = stop_gate.handle(self.event())
        self.assertEqual(self.runs, 1)
        self.assertEqual(second["decision"], "block")
        self.assertIn("bad-crit", second["reason"])
        self.assertEqual(first["reason"], second["reason"])

    def test_an_edited_file_runs_it_again(self) -> None:
        self.passing()
        self.set_pipeline("build")
        self.cli_run()
        (self.root / "src" / "app.py").write_text("x = 22\n", encoding="utf-8")
        stop_gate.handle(self.event())
        self.assertEqual(self.runs, 2)

    def test_an_added_or_a_removed_file_runs_it_again(self) -> None:
        self.passing()
        self.set_pipeline("build")
        self.cli_run()
        (self.root / "src" / "new.py").write_text("", encoding="utf-8")
        stop_gate.handle(self.event())
        self.assertEqual(self.runs, 2)
        (self.root / "src" / "new.py").unlink()
        stop_gate.handle(self.event())
        self.assertEqual(self.runs, 3)

    def test_a_derived_contract_runs_it_again(self) -> None:
        self.passing()
        self.set_pipeline("build")
        self.cli_run()
        self.write_contract({"id": "other-crit", "argv": [PY, "-c", "pass"], "timeout_s": 20})
        stop_gate.handle(self.event())
        self.assertEqual(self.runs, 2)

    def test_a_stale_contract_is_never_reused(self) -> None:
        self.passing()
        self.set_pipeline("build")
        self.cli_run()
        self.gate_md.write_text(self.gate_md.read_text(encoding="utf-8") + "\nedited\n",
                                encoding="utf-8")
        self.assertIsNone(contract.reusable(self.root))
        result = stop_gate.handle(self.event())
        self.assertEqual(result["decision"], "block")

    def test_an_old_run_is_not_reused(self) -> None:
        self.passing()
        self.set_pipeline("build")
        self.cli_run()
        record = contract.last_run_file(self.root)
        data = json.loads(record.read_text(encoding="utf-8"))
        data["ran_at"] -= contract.REUSE_MAX_AGE_S + 60
        record.write_text(json.dumps(data), encoding="utf-8")
        stop_gate.handle(self.event())
        self.assertEqual(self.runs, 2)

    def test_caches_and_gatekit_state_do_not_count_as_a_change(self) -> None:
        self.passing()
        self.set_pipeline("build")
        self.cli_run()
        cache = self.root / "src" / "__pycache__"
        cache.mkdir()
        (cache / "app.cpython-314.pyc").write_bytes(b"x")
        (self.root / ".gatekit" / "runs" / "note.txt").write_text("x", encoding="utf-8")
        stop_gate.handle(self.event())
        self.assertEqual(self.runs, 1)

    def test_a_tree_too_large_to_fingerprint_is_never_reused(self) -> None:
        self.passing()
        self.set_pipeline("build")
        original = contract.FINGERPRINT_MAX_FILES
        contract.FINGERPRINT_MAX_FILES = 1
        try:
            self.cli_run()
            self.assertIsNone(contract.reusable(self.root))
            stop_gate.handle(self.event())
        finally:
            contract.FINGERPRINT_MAX_FILES = original
        self.assertEqual(self.runs, 2)

    def test_a_run_cut_by_an_explicit_budget_is_not_recorded(self) -> None:
        self.passing()
        contract.run(["run", "--budget", "30", "--root", str(self.root)])
        self.assertFalse(contract.last_run_file(self.root).exists())

    def test_a_record_that_is_not_a_result_is_ignored(self) -> None:
        self.passing()
        self.set_pipeline("build")
        self.cli_run()
        record = contract.last_run_file(self.root)
        for junk in ("not json", "[]", json.dumps({"ran_at": "now", "result": {}})):
            record.write_text(junk, encoding="utf-8")
            self.assertIsNone(contract.reusable(self.root), junk)


class TestUnmanagedProject(unittest.TestCase):
    """No `.gatekit/` means no contract to run and no state left behind."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".git").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_stop_allows_and_leaves_no_state(self) -> None:
        event = {"session_id": "u", "cwd": str(self.root),
                 "hook_event_name": "Stop"}
        self.assertIsNone(stop_gate.handle(event))
        self.assertFalse((self.root / ".gatekit").exists())
