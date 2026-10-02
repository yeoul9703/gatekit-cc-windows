"""Tests for gates/stop.py — contract-enforced completion."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import approval, contract, ledger  # noqa: E402
from gatekit.gates import stop as stop_gate  # noqa: E402
from tests import isolation  # noqa: E402

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

    def write_gate(self, *criteria: dict) -> None:
        body = "# Gate\n\n" + "".join(
            "```gatekit-criterion\n" + json.dumps(c) + "\n```\n" for c in criteria
        )
        self.gate_md.write_text(body, encoding="utf-8")

    def approve(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")

    def write_contract(self, *criteria: dict) -> None:
        """The state /gatekit-gate leaves: criteria written, approved, derived."""
        self.write_gate(*criteria)
        self.approve()
        contract.derive(self.root)

    def edit_contract_json(self, argv: list) -> None:
        """Rewrite the frozen criteria by hand; the recorded gate hash stays."""
        target = self.root / ".gatekit" / "contract.json"
        data = json.loads(target.read_text(encoding="utf-8"))
        for crit in data["criteria"]:
            crit["argv"] = argv
        target.write_text(json.dumps(data), encoding="utf-8")

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
        # The approval holds; a design input changed after the contract was derived.
        self.passing()
        self.set_pipeline("build")
        (self.root / "spec" / "02-design.md").write_text("# design\n", encoding="utf-8")
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertIn("contract_stale", result["reason"])

    def test_reapproved_gate_not_derived_again_is_stale(self) -> None:
        self.passing()
        self.set_pipeline("build")
        self.gate_md.write_text(
            self.gate_md.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8"
        )
        self.approve()
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertIn("contract_stale", result["reason"])


class TestLanguage(StopProject):
    def test_korean_reason_by_default(self) -> None:
        self.failing()
        self.set_pipeline("build")
        reason = stop_gate.handle(self.event())["reason"]
        self.assertIn("완료 계약을 충족하지 못했으므로", reason)
        self.assertNotIn("the completion contract is not met", reason)

    def test_korean_stale_reason_by_default(self) -> None:
        self.passing()
        self.set_pipeline("build")
        (self.root / "spec" / "02-design.md").write_text("# design\n", encoding="utf-8")
        reason = stop_gate.handle(self.event())["reason"]
        self.assertIn("판정할 수 없습니다", reason)
        self.assertIn("contract derive", reason)


class TestSubprocess(StopProject):
    def _run(self, event: dict) -> "tuple[int, str, str]":
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        # The reason is Korean. The registered hook goes through bin/gatekit.py, which
        # makes stdout UTF-8; the script run on its own takes the encoding from here.
        env["PYTHONIOENCODING"] = "utf-8"
        proc = isolation.run_gate(
            [sys.executable, str(GATE_SCRIPT)],
            cwd=self.root,
            input=json.dumps(event),
            capture_output=True,
            text=True,
            encoding="utf-8",
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
        self.assertIn("bad-crit", payload["reason"])
        self.assertIn("완료 계약", payload["reason"])

    def test_loosened_gate_file_blocks_via_subprocess(self) -> None:
        self.failing()
        self.set_pipeline("build")
        self.write_gate({"id": "bad-crit", "argv": [PY, "-c", "pass"], "timeout_s": 20})
        contract.derive(self.root)
        code, out, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("승인이 유효하지 않아", payload["reason"])

    def test_edited_contract_json_blocks_via_subprocess(self) -> None:
        self.failing()
        self.set_pipeline("build")
        self.edit_contract_json([PY, "-c", "pass"])
        code, out, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("contract derive", payload["reason"])

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
        # No event means no cwd: the gate takes the project of its working directory,
        # and in a managed project it records the stop under "unknown-session".
        proc = isolation.run_gate(
            [sys.executable, str(GATE_SCRIPT)],
            cwd=self.root,
            input="{oops",
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(ledger.Ledger.exists(self.root, "unknown-session"))


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
        self.approve()
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
        self.approve()
        self.assertIsNone(contract.reusable(self.root))
        result = stop_gate.handle(self.event())
        self.assertEqual(result["decision"], "block")
        self.assertIn("contract_stale", result["reason"])

    def test_an_unapproved_gate_runs_nothing_and_reuses_nothing(self) -> None:
        # A passing run of the re-derived contract is on record and reusable.
        # The gate file is not the approved one, so the record does not decide
        # and no criterion runs either.
        self.passing()
        self.set_pipeline("build")
        self.gate_md.write_text(self.gate_md.read_text(encoding="utf-8") + "\nedited\n",
                                encoding="utf-8")
        contract.derive(self.root)
        self.cli_run()
        self.assertIsNotNone(contract.reusable(self.root))
        result = stop_gate.handle(self.event())
        self.assertEqual(result["decision"], "block")
        self.assertEqual(self.runs, 1)
        self.assertNotEqual(self.led().data["stop"]["final_verdict"], "ok")

    def test_a_run_recorded_from_an_edited_contract_is_not_reused(self) -> None:
        # contract.json edited to pass, then `contract run` records ok for exactly
        # that file. The record matches the file byte for byte; the gate still
        # refuses, because the file is not what spec/05-gate.md states.
        self.failing()
        self.set_pipeline("build")
        self.edit_contract_json([PY, "-c", "pass"])
        self.cli_run()
        self.assertIsNotNone(contract.reusable(self.root))
        result = stop_gate.handle(self.event())
        self.assertEqual(result["decision"], "block")
        self.assertEqual(self.runs, 1)
        self.assertNotEqual(self.led().data["stop"]["final_verdict"], "ok")

    def test_an_approved_unchanged_project_still_reuses(self) -> None:
        # The two checks before the run do not cost a run of their own.
        self.passing()
        self.set_pipeline("build")
        self.cli_run()
        for _ in range(3):
            self.assertIsNone(stop_gate.handle(self.event()))
        self.assertEqual(self.runs, 1)

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


class TestApprovedCriteriaOnly(StopProject):
    """The stop is judged on the criteria the user approved, or not at all.

    Both roads were walked against the old gate and let the session end with
    ``final_verdict: ok``: edit ``contract.json``, or loosen ``spec/05-gate.md``
    and derive again. ``contract status`` says ``ok`` on both.
    """

    PASS = [PY, "-c", "pass"]

    def loosen_gate_and_derive(self) -> None:
        self.write_gate({"id": "bad-crit", "argv": self.PASS, "timeout_s": 20})
        contract.derive(self.root)

    def stop_state(self) -> dict:
        return self.led().data["stop"]

    def test_gate_file_loosened_after_approval_blocks(self) -> None:
        self.failing()
        self.set_pipeline("build")
        self.assertIn("bad-crit", stop_gate.handle(self.event())["reason"])
        self.loosen_gate_and_derive()
        self.assertEqual(contract.status(self.root), "ok")
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "fail")
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertEqual(result["decision"], "block")
        self.assertIn("/gatekit-gate", result["reason"])
        self.assertIn("fail", result["reason"])
        self.assertEqual(self.stop_state()["last_reasons"], [contract.UNAPPROVED_REASON])
        self.assertNotEqual(self.stop_state()["final_verdict"], "ok")

    def test_contract_json_edited_after_approval_blocks(self) -> None:
        self.failing()
        self.set_pipeline("build")
        self.assertIn("bad-crit", stop_gate.handle(self.event())["reason"])
        self.edit_contract_json(self.PASS)
        self.assertEqual(contract.status(self.root), "ok")
        self.assertEqual(approval.check(self.root, "spec/05-gate.md"), "ok")
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertEqual(result["decision"], "block")
        self.assertIn("contract derive", result["reason"])
        self.assertIn("/gatekit-gate", result["reason"])
        self.assertEqual(self.stop_state()["last_reasons"], [contract.MISMATCH_REASON])
        self.assertNotEqual(self.stop_state()["final_verdict"], "ok")

    def test_a_raised_budget_in_contract_json_blocks(self) -> None:
        self.passing()
        self.set_pipeline("build")
        target = self.root / ".gatekit" / "contract.json"
        data = json.loads(target.read_text(encoding="utf-8"))
        data["total_budget_s"] = 600
        target.write_text(json.dumps(data), encoding="utf-8")
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertIn("contract_mismatch", result["reason"])

    def test_never_approved_gate_blocks(self) -> None:
        self.write_gate({"id": "ok-crit", "argv": self.PASS, "timeout_s": 20})
        contract.derive(self.root)
        self.set_pipeline("build")
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertIn("unverified", result["reason"])
        self.assertIn("/gatekit-gate", result["reason"])

    def test_deriving_again_judges_by_the_gate_file(self) -> None:
        # The way the mismatch message names: after it, the approved criteria decide.
        self.failing()
        self.set_pipeline("build")
        self.edit_contract_json(self.PASS)
        stop_gate.handle(self.event())
        contract.derive(self.root)
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertIn("bad-crit", result["reason"])

    def test_approving_again_opens_the_stop(self) -> None:
        # The way the approval message names: /gatekit-gate approves and derives.
        self.failing()
        self.set_pipeline("build")
        self.loosen_gate_and_derive()
        self.assertIsNotNone(stop_gate.handle(self.event()))
        self.approve()
        self.assertIsNone(stop_gate.handle(self.event()))
        self.assertEqual(self.stop_state()["final_verdict"], "ok")

    def test_putting_the_approved_criteria_back_judges_the_code(self) -> None:
        self.failing()
        self.set_pipeline("build")
        approved = self.gate_md.read_bytes()
        self.loosen_gate_and_derive()
        self.assertIn("/gatekit-gate", stop_gate.handle(self.event())["reason"])
        self.gate_md.write_bytes(approved)
        contract.derive(self.root)
        self.assertIn("bad-crit", stop_gate.handle(self.event())["reason"])

    def test_messages_say_the_way_out_in_korean(self) -> None:
        self.failing()
        self.set_pipeline("build")
        failing = stop_gate.handle(self.event())["reason"]
        self.edit_contract_json(self.PASS)
        edited = stop_gate.handle(self.event())["reason"]
        self.loosen_gate_and_derive()
        unapproved = stop_gate.handle(self.event())["reason"]
        for reason in (failing, edited, unapproved):
            self.assertIn("코드를 고", reason)  # 고친 뒤 / 고치세요
            self.assertIn("/gatekit-gate 로 돌아가 사용자에게 다시 승인받으세요", reason)
        self.assertIn("승인이 유효하지 않아", unapproved)
        self.assertIn("승인 상태: fail", unapproved)
        self.assertIn("contract.json 의 기준이", edited)

    def test_both_languages_have_every_message_and_none_cites_a_decision_number(self) -> None:
        tables = stop_gate._MESSAGES
        self.assertEqual(sorted(tables["en"]), sorted(tables["ko"]))
        for table in tables.values():
            for text in table.values():
                self.assertNotRegex(text, r"ADR-\d")


class TestStandingDown(StopProject):
    """Where the gate does not block it still never records a pass it did not see."""

    PASS = [PY, "-c", "pass"]

    def unapproved(self) -> None:
        self.failing()
        self.set_pipeline("build")
        self.write_gate({"id": "bad-crit", "argv": self.PASS, "timeout_s": 20})
        contract.derive(self.root)

    def edited(self) -> None:
        self.failing()
        self.set_pipeline("build")
        self.edit_contract_json(self.PASS)

    def final(self) -> str:
        return self.led().data["stop"]["final_verdict"]

    def test_three_blocks_then_unverified(self) -> None:
        for name, arrange in (("unapproved", self.unapproved), ("edited", self.edited)):
            with self.subTest(name):
                self.session = "sess-" + name
                arrange()
                for _ in range(stop_gate.MAX_BLOCKS):
                    self.assertIsNotNone(stop_gate.handle(self.event()))
                self.assertIsNone(stop_gate.handle(self.event()))
                self.assertEqual(self.final(), "unverified")

    def test_stop_hook_active_allows_and_records_unverified(self) -> None:
        for name, arrange in (("unapproved", self.unapproved), ("edited", self.edited)):
            with self.subTest(name):
                self.session = "sess-" + name
                arrange()
                self.assertIsNone(stop_gate.handle(self.event(stop_hook_active=True)))
                self.assertEqual(self.final(), "unverified")
                self.assertEqual(self.led().data["stop"]["block_count"], 0)

    def test_no_pipeline_is_unverified_even_when_unapproved(self) -> None:
        self.failing()
        self.write_gate({"id": "bad-crit", "argv": self.PASS, "timeout_s": 20})
        contract.derive(self.root)
        self.assertIsNone(stop_gate.handle(self.event()))
        self.assertEqual(self.final(), "unverified")

    def test_no_contract_is_unverified(self) -> None:
        self.set_pipeline("build")
        self.assertIsNone(stop_gate.handle(self.event()))
        self.assertEqual(self.final(), "unverified")

    def test_project_without_spec_is_unverified(self) -> None:
        (self.root / "spec").rmdir()
        self.set_pipeline("build")
        self.assertIsNone(stop_gate.handle(self.event()))
        self.assertEqual(self.final(), "unverified")


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
