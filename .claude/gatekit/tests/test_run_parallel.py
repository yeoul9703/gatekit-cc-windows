"""tests/run_parallel.py, the per-class parallel test runner.

The runner tests write a throwaway test package into a temp folder and run the runner on it
(`--dir`) as a subprocess, so nothing here starts the real suite.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from tests import run_parallel

RUNNER = pathlib.Path(run_parallel.__file__).resolve()
RAN = re.compile(r"^Ran (\d+) tests? in \d+\.\d{3}s$", re.M)
FAILED = re.compile(r"^FAILED \(failures=(\d+), errors=(\d+)(?:, skipped=\d+)?\)$", re.M)

QUICK = """
import unittest

class Quick(unittest.TestCase):
    def test_one(self):
        pass

    def test_two(self):
        pass
"""

# 2 + 2 + 1 = 5 tests: failures=1, errors=1
ALPHA = """
import unittest

class Good(unittest.TestCase):
    def test_one(self):
        print("PASSING-CLASS-MARKER")

    def test_two(self):
        pass

class OneFailure(unittest.TestCase):
    def test_fails(self):
        self.fail("FAILURE-MARKER-ALPHA")

    def test_passes(self):
        pass

class OneError(unittest.TestCase):
    def test_raises(self):
        raise RuntimeError("ERROR-MARKER-ALPHA")
"""

# 4 + 2 + 1 + 1 = 8 tests: failures=1+2+1 (the unexpected success counts), errors=1, skipped=1
BETA = """
import unittest

class Mixed(unittest.TestCase):
    def test_fails(self):
        self.assertEqual(1, 2, "FAILURE-MARKER-BETA")

    def test_raises(self):
        raise ValueError("ERROR-MARKER-BETA")

    @unittest.skip("not today")
    def test_skipped(self):
        pass

    def test_passes(self):
        pass

class TwoFailures(unittest.TestCase):
    def test_a(self):
        self.assertTrue(False)

    def test_b(self):
        self.assertIn("x", "y")

class Surprise(unittest.TestCase):
    @unittest.expectedFailure
    def test_passes_anyway(self):
        pass

class ExpectedFailure(unittest.TestCase):
    @unittest.expectedFailure
    def test_fails_as_expected(self):
        self.fail("expected")
"""

SLOW = """
import unittest

class Slow(unittest.TestCase):
    def test_fails(self):
        self.fail("SLOW-MODULE-RAN %s")
"""


class RunnerCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.pkg = pathlib.Path(tmp.name) / "gk_fake_suite"
        self.pkg.mkdir()
        (self.pkg / "__init__.py").write_text("", encoding="utf-8")

    def write(self, module: str, body: str) -> None:
        (self.pkg / (module + ".py")).write_text(textwrap.dedent(body), encoding="utf-8")

    def run_runner(self, *args: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RUNNER), "--dir", str(self.pkg), "--workers", "4", *args],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False)

    def ran(self, proc: subprocess.CompletedProcess[str]) -> int:
        found = RAN.findall(proc.stdout)
        self.assertTrue(found, proc.stdout + proc.stderr)
        return int(found[-1])

    def last_line(self, proc: subprocess.CompletedProcess[str]) -> str:
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertTrue(lines, proc.stderr)
        return lines[-1]

    def failed_counts(self, proc: subprocess.CompletedProcess[str]) -> tuple[int, int]:
        match = FAILED.search(self.last_line(proc))
        self.assertIsNotNone(match, proc.stdout)
        assert match is not None
        return int(match.group(1)), int(match.group(2))


class TestCounting(RunnerCase):
    def test_failures_and_errors_are_summed_across_classes_and_modules(self) -> None:
        self.write("test_alpha", ALPHA)
        self.write("test_beta", BETA)
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertEqual(self.ran(proc), 13)
        self.assertEqual(self.failed_counts(proc), (5, 2))
        self.assertEqual(self.last_line(proc), "FAILED (failures=5, errors=2, skipped=1)")

    def test_output_of_a_class_that_did_not_pass_is_shown_and_a_passing_class_is_not(self) -> None:
        self.write("test_alpha", ALPHA)
        self.write("test_beta", BETA)
        out = self.run_runner().stdout
        for marker in ("FAILURE-MARKER-ALPHA", "ERROR-MARKER-ALPHA", "FAILURE-MARKER-BETA",
                       "ERROR-MARKER-BETA", "Traceback (most recent call last)"):
            self.assertIn(marker, out)
        self.assertNotIn("PASSING-CLASS-MARKER", out)
        self.assertIn("Classes that did not pass (5):", out)
        self.assertNotIn("gk_fake_suite.test_alpha.Good (", out)
        self.assertNotIn("gk_fake_suite.test_beta.ExpectedFailure (", out)

    def test_everything_passing_exits_0_with_ok(self) -> None:
        self.write("test_quick", QUICK)
        self.write("test_more", QUICK.replace("Quick", "More"))
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.ran(proc), 4)
        self.assertEqual(self.last_line(proc), "OK")

    def test_a_module_that_does_not_import_is_one_error(self) -> None:
        self.write("test_quick", QUICK)
        self.write("test_broken", "import unittest\ndef broken(:\n    pass\n")
        proc = self.run_runner()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertEqual(self.ran(proc), 3)
        self.assertEqual(self.failed_counts(proc), (0, 1))
        self.assertIn("SyntaxError", proc.stdout)


class TestFast(RunnerCase):
    def test_slow_modules_constant_holds_the_powershell_heavy_modules(self) -> None:
        self.assertEqual(set(run_parallel.SLOW_MODULES), {
            "test_scripts", "test_setup_packages", "test_setup_reinstall", "test_packages",
            "test_session_check"})

    def test_fast_skips_every_slow_module(self) -> None:
        for name in run_parallel.SLOW_MODULES:
            self.write(name, SLOW % name)
        self.write("test_quick", QUICK)
        proc = self.run_runner("--fast")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.ran(proc), 2)
        self.assertEqual(self.last_line(proc), "OK")
        self.assertNotIn("SLOW-MODULE-RAN", proc.stdout)

        full = self.run_runner()
        self.assertEqual(full.returncode, 1, full.stdout)
        self.assertEqual(self.ran(full), 2 + len(run_parallel.SLOW_MODULES))
        self.assertEqual(self.failed_counts(full), (len(run_parallel.SLOW_MODULES), 0))

    def test_fast_ignores_a_slow_module_that_has_no_file(self) -> None:
        self.write("test_quick", QUICK)
        proc = self.run_runner("--fast")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(self.ran(proc), 2)

    def test_fast_with_only_slow_modules_named_has_nothing_to_run_and_fails(self) -> None:
        self.write("test_scripts", SLOW % "test_scripts")
        proc = self.run_runner("--fast", "test_scripts")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("nothing to run", proc.stdout)
        self.assertIsNone(RAN.search(proc.stdout))
        self.assertNotIn("SLOW-MODULE-RAN", proc.stdout)


class TestSelection(RunnerCase):
    def test_named_modules_run_alone_in_any_spelling(self) -> None:
        self.write("test_alpha", ALPHA)
        self.write("test_quick", QUICK)
        for spelling in ("test_quick", "gk_fake_suite.test_quick", "gk_fake_suite/test_quick.py"):
            proc = self.run_runner(spelling)
            self.assertEqual(proc.returncode, 0, spelling + ": " + proc.stdout)
            self.assertEqual(self.ran(proc), 2, spelling)

    def test_unknown_module_is_a_usage_error(self) -> None:
        self.write("test_quick", QUICK)
        proc = self.run_runner("test_nope")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("unknown test module", proc.stderr)


class TestTimeout(RunnerCase):
    def test_a_class_past_the_limit_is_killed_and_counted_as_one_error(self) -> None:
        self.write("test_quick", QUICK)
        self.write("test_hang", """
            import time
            import unittest

            class Hangs(unittest.TestCase):
                def test_sleeps(self):
                    time.sleep(120)
            """)
        start = time.monotonic()
        proc = self.run_runner("--timeout", "3", timeout=110)
        self.assertLess(time.monotonic() - start, 60)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertEqual(self.failed_counts(proc), (0, 1))
        self.assertEqual(self.ran(proc), 3)
        self.assertIn("gk_fake_suite.test_hang.Hangs (timed out after 3s", proc.stdout)


class TestSummaryParsing(unittest.TestCase):
    def summarize(self, output: str, code: int | None, count: int = 4) -> run_parallel.Result:
        job = run_parallel.Job("pkg.test_x.Case", "test_x", count)
        return run_parallel.summarize(run_parallel.Result(job, code, 0.1, output))

    def test_ok_with_skips(self) -> None:
        result = self.summarize("....\n---\nRan 4 tests in 0.010s\n\nOK (skipped=2)\n", 0)
        self.assertEqual((result.ran, result.failures, result.errors, result.skipped), (4, 0, 0, 2))
        self.assertTrue(result.passed)

    def test_failed_counts_unexpected_successes_as_failures(self) -> None:
        result = self.summarize("Ran 5 tests in 1.000s\n\nFAILED (errors=2, unexpected successes=1)\n", 1)
        self.assertEqual((result.ran, result.failures, result.errors), (5, 1, 2))

    def test_a_later_ok_printed_by_a_test_does_not_hide_the_verdict(self) -> None:
        result = self.summarize("Ran 2 tests in 0.1s\n\nFAILED (failures=1)\nOK\n", 1)
        self.assertEqual((result.failures, result.errors), (1, 0))

    def test_no_summary_is_one_error(self) -> None:
        result = self.summarize("Fatal Python error: boom\n", 3, count=7)
        self.assertEqual((result.ran, result.failures, result.errors), (7, 0, 1))
        self.assertIn("exit code 3", result.problem)

    def test_no_tests_ran_is_one_error(self) -> None:
        result = self.summarize("\nRan 0 tests in 0.000s\n\nNO TESTS RAN\n", 5, count=0)
        self.assertEqual((result.ran, result.errors), (1, 1))

    def test_ok_with_a_nonzero_exit_code_is_one_error(self) -> None:
        result = self.summarize("Ran 1 test in 0.1s\n\nOK\n", 1)
        self.assertEqual(result.errors, 1)
        self.assertIn("OK but exit code 1", result.problem)

    def test_verdict_line_always_names_failures_and_errors(self) -> None:
        self.assertEqual(run_parallel.verdict_line(0, 0, 0), "OK")
        self.assertEqual(run_parallel.verdict_line(0, 0, 3), "OK (skipped=3)")
        self.assertEqual(run_parallel.verdict_line(2, 0, 0), "FAILED (failures=2, errors=0)")
        self.assertEqual(run_parallel.verdict_line(0, 1, 4), "FAILED (failures=0, errors=1, skipped=4)")

    def test_schedule_starts_slow_modules_then_bigger_classes(self) -> None:
        jobs = [run_parallel.Job("t.test_a.Small", "test_a", 1),
                run_parallel.Job("t.test_a.Big", "test_a", 9),
                run_parallel.Job("t.test_scripts.Tiny", "test_scripts", 1)]
        self.assertEqual([j.target for j in run_parallel.schedule(jobs)],
                         ["t.test_scripts.Tiny", "t.test_a.Big", "t.test_a.Small"])


if __name__ == "__main__":
    unittest.main()
