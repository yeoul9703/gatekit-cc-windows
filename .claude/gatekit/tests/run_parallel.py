"""Run the unit tests in parallel: one `python -m unittest <module>.<Class>` child per test class.

Run from .claude/gatekit:

    uv run --frozen python tests/run_parallel.py [--workers N] [--fast] [--timeout SEC] [module ...]

    module      run only these test modules (test_doctor, tests.test_doctor or tests/test_doctor.py)
    --workers   classes run at the same time (default 8)
    --fast      skip SLOW_MODULES, the modules that start PowerShell scripts many times
    --timeout   seconds one class may take; past it its whole process tree is killed and the
                class counts as one error (default 600)
    --dir       the test package to run (default: the folder of this file)

Classes are collected by importing each module (the same TestCase subclasses
`unittest discover` would load), started slowest-first, and each child's stdout and stderr go
to a temp file, so a leftover grandchild holding an inherited handle cannot stall the run.
The output of every class that did not pass is printed as it was written. The report ends like
unittest's: `Ran N tests in X.XXXs`, then `OK` or `FAILED (failures=a, errors=b)`.

Exit code: 0 every class passed, 1 anything failed (a failure, an error, a class that crashed or
ran past --timeout, or nothing to run), 2 usage error. Standard library only.
"""
from __future__ import annotations

import argparse
import importlib
import locale
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

# Skipped by --fast: these modules start Windows PowerShell scripts many times.
# A name without a file is ignored.
SLOW_MODULES = (
    "test_scripts",
    "test_setup_packages",
    "test_setup_reinstall",
    "test_packages",
    "test_session_check",
)
DEFAULT_WORKERS = 8
DEFAULT_TIMEOUT = 600  # seconds per class
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
LINE = "-" * 70
DOUBLE_LINE = "=" * 70
DOTS_PER_LINE = 70

_running: set[subprocess.Popen[bytes]] = set()
_running_lock = threading.Lock()


@dataclass
class Job:
    target: str   # dotted name given to `python -m unittest`
    module: str   # bare module name, e.g. test_doctor
    count: int    # tests collected; 0 when the module did not import (the child reports why)


@dataclass
class Result:
    job: Job
    code: int | None
    seconds: float
    output: str
    ran: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    problem: str = ""   # why the class did not pass, when its unittest summary does not say
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.failures == 0 and self.errors == 0


def module_names(test_dir: str) -> list[str]:
    """The modules `unittest discover` would load: test*.py directly in *test_dir*."""
    return sorted(name[:-3] for name in os.listdir(test_dir)
                  if name.startswith("test") and name.endswith(".py")
                  and os.path.isfile(os.path.join(test_dir, name)))


def normalize_module(name: str, package: str) -> str:
    base = name.replace("\\", "/").rstrip("/").split("/")[-1]
    if base.endswith(".py"):
        base = base[:-3]
    if base.startswith(package + "."):
        base = base[len(package) + 1:]
    return base


def collect(test_dir: str, modules: list[str]) -> list[Job]:
    """One job per TestCase subclass with tests, in the order unittest loads them."""
    package = os.path.basename(test_dir)
    parent = os.path.dirname(test_dir)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    loader = unittest.TestLoader()
    jobs: list[Job] = []
    for module_name in modules:
        dotted = package + "." + module_name
        try:
            module = importlib.import_module(dotted)
        except (Exception, SystemExit):
            # Run the bare module: unittest turns the import error into one error.
            jobs.append(Job(dotted, module_name, 0))
            continue
        for attr in dir(module):   # loadTestsFromModule walks dir() too
            obj = getattr(module, attr, None)
            if isinstance(obj, type) and issubclass(obj, unittest.TestCase):
                count = loader.loadTestsFromTestCase(obj).countTestCases()
                if count:
                    jobs.append(Job(dotted + "." + attr, module_name, count))
    return jobs


def schedule(jobs: list[Job]) -> list[Job]:
    """Slowest first: the longest single class bounds the wall time."""
    return sorted(jobs, key=lambda j: (j.module not in SLOW_MODULES, -j.count, j.target))


def kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Kill *proc* and its children (a plain kill leaves grandchildren running)."""
    if os.name == "nt":
        taskkill = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "taskkill.exe")
        try:
            subprocess.run([taskkill, "/T", "/F", "/PID", str(proc.pid)], stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(proc.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def decode(data: bytes) -> str:
    """Child output as text with \\n line ends (printing \\r\\n again would double the \\r)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode(locale.getpreferredencoding(False), errors="replace")
    return text.replace("\r\n", "\n")


def parse_counts(text: str) -> dict[str, int]:
    """'failures=1, errors=2, skipped=3' -> {'failures': 1, 'errors': 2, 'skipped': 3}"""
    counts: dict[str, int] = {}
    for part in text.split(","):
        key, _, value = part.strip().partition("=")
        if value.strip().isdigit():
            counts[key.strip()] = int(value)
    return counts


def summarize(result: Result) -> Result:
    """Fill ran/failures/errors/skipped from the child's unittest summary.

    The summary is the last `Ran N tests in` line and the first non-empty line after it
    (unittest writes both to stderr back to back). A class without one, or whose verdict
    disagrees with its exit code, counts as one error."""
    lines = result.output.splitlines()
    ran_at = -1
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("Ran ") and " test" in lines[i] and " in " in lines[i]:
            ran_at = i
            break
    verdict = ""
    if ran_at >= 0:
        words = lines[ran_at].split()
        if len(words) > 1 and words[1].isdigit():
            result.ran = int(words[1])
        for line in lines[ran_at + 1:]:
            if line.strip():
                verdict = line.strip()
                break
    word, _, rest = verdict.partition(" ")
    if word in ("OK", "FAILED"):
        result.counts = parse_counts(rest.strip().strip("()"))
    result.skipped = result.counts.get("skipped", 0)
    if word == "OK" and result.code == 0:
        return result
    if word == "FAILED":
        result.failures = result.counts.get("failures", 0) + result.counts.get("unexpected successes", 0)
        result.errors = result.counts.get("errors", 0)
        if result.failures + result.errors == 0:
            result.errors = 1
            result.problem = "FAILED without a failure count (exit code %s)" % result.code
        return result
    # Crashed, no tests ran (exit code 5), or an OK that exited non-zero.
    result.errors = 1
    result.ran = max(result.ran, result.job.count, 1)
    if not result.problem:
        if word == "OK":
            result.problem = "OK but exit code %s" % result.code
        else:
            result.problem = "no unittest summary (exit code %s)" % result.code
    return result


def run_job_safely(job: Job, cwd: str, env: dict[str, str], timeout: float) -> Result:
    """run_job, with a runner-side exception reported as one error of that class."""
    try:
        return run_job(job, cwd, env, timeout)
    except Exception as exc:  # keep the other classes running
        result = Result(job, None, 0.0, "runner error: %r\n" % (exc,))
        result.problem = "runner error: %s" % (exc,)
        result.errors = 1
        result.ran = max(job.count, 1)
        return result


def run_job(job: Job, cwd: str, env: dict[str, str], timeout: float) -> Result:
    cmd = [sys.executable, "-m", "unittest", job.target]
    extra = {} if os.name == "nt" else {"start_new_session": True}
    start = time.monotonic()
    with tempfile.TemporaryFile() as out:
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                    stderr=subprocess.STDOUT, **extra)
        except OSError as exc:
            result = Result(job, None, time.monotonic() - start, "%s\n" % exc)
            result.problem = "could not start: %s" % exc
            return summarize(result)
        with _running_lock:
            _running.add(proc)
        timed_out = False
        try:
            code: int | None = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(proc)
            try:
                code = proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                code = None
        finally:
            with _running_lock:
                _running.discard(proc)
        out.seek(0)
        text = decode(out.read())
    result = Result(job, code, time.monotonic() - start, text)
    if timed_out:
        result.problem = "timed out after %ds, process tree killed" % timeout
        result.errors = 1
        result.ran = max(job.count, 1)
        return result
    return summarize(result)


def stop_running() -> None:
    with _running_lock:
        procs = list(_running)
    for proc in procs:
        kill_tree(proc)


def mark(result: Result) -> str:
    if result.passed:
        return "."
    return "F" if result.failures and not result.errors else "E"


def describe(result: Result) -> str:
    if result.problem:
        return result.problem
    return "failures=%d, errors=%d, exit code %s" % (result.failures, result.errors, result.code)


def verdict_line(failures: int, errors: int, skipped: int) -> str:
    if failures == 0 and errors == 0:
        return "OK (skipped=%d)" % skipped if skipped else "OK"
    extra = ", skipped=%d" % skipped if skipped else ""
    return "FAILED (failures=%d, errors=%d%s)" % (failures, errors, extra)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the unit tests in parallel, one subprocess per test class.")
    parser.add_argument("modules", nargs="*", metavar="module",
                        help="test modules to run (default: every test*.py)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help="classes run at the same time (default %d)" % DEFAULT_WORKERS)
    parser.add_argument("--fast", action="store_true",
                        help="skip the slow integration modules: " + ", ".join(SLOW_MODULES))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help="seconds one class may take (default %d)" % DEFAULT_TIMEOUT)
    parser.add_argument("--dir", default=TESTS_DIR,
                        help="test package folder (default: the folder of this file)")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    test_dir = os.path.abspath(args.dir)
    if not os.path.isfile(os.path.join(test_dir, "__init__.py")):
        parser.error("%s is not a test package (no __init__.py)" % test_dir)
    package = os.path.basename(test_dir)
    available = module_names(test_dir)
    if args.modules:
        wanted = []
        for name in args.modules:
            module = normalize_module(name, package)
            if module not in available:
                parser.error("unknown test module: %s" % name)
            if module not in wanted:
                wanted.append(module)
    else:
        wanted = available
    skipped_modules: list[str] = []
    if args.fast:
        skipped_modules = [m for m in wanted if m in SLOW_MODULES]
        wanted = [m for m in wanted if m not in SLOW_MODULES]

    env = dict(os.environ)   # before any test module is imported
    jobs = schedule(collect(test_dir, wanted))
    if not jobs:
        print("nothing to run: no test classes in %s" % (", ".join(wanted) or "(no modules)"))
        if skipped_modules:
            print("--fast skipped: " + ", ".join(skipped_modules))
        return 1

    workers = min(args.workers, len(jobs))
    total = sum(j.count for j in jobs)
    print("Running %d tests in %d classes, %d at a time" % (total, len(jobs), workers))
    if skipped_modules:
        print("--fast: skipped the slow integration modules " + ", ".join(skipped_modules))
    sys.stdout.flush()

    cwd = os.path.dirname(test_dir)
    results: list[Result] = []
    start = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        pending: set[Future[Result]] = {pool.submit(run_job_safely, job, cwd, env, args.timeout)
                                        for job in jobs}
        while pending:
            # A short wait keeps the main thread responsive to Ctrl+C on Windows.
            done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            for future in done:
                result = future.result()
                results.append(result)
                sys.stdout.write(mark(result))
                if len(results) % DOTS_PER_LINE == 0:
                    sys.stdout.write("\n")
                sys.stdout.flush()
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        stop_running()
        print("\ninterrupted: stopped the running classes")
        return 1
    pool.shutdown(wait=True)
    elapsed = time.monotonic() - start
    if len(results) % DOTS_PER_LINE:
        print()

    by_name = sorted(results, key=lambda r: r.job.target)
    bad = [r for r in by_name if not r.passed]
    for result in bad:
        print(DOUBLE_LINE)
        print("NOT PASSED: %s (%s, %.1fs)" % (result.job.target, describe(result), result.seconds))
        print(LINE)
        print(result.output.rstrip("\r\n") or "(no output)")
    slowest = sorted(results, key=lambda r: -r.seconds)[:3]
    print(DOUBLE_LINE)
    print("slowest: " + ", ".join("%s %.1fs" % (r.job.target, r.seconds) for r in slowest))
    if bad:
        print("Classes that did not pass (%d):" % len(bad))
        for result in bad:
            print("  %s (%s)" % (result.job.target, describe(result)))
    ran = sum(r.ran for r in results)
    failures = sum(r.failures for r in results)
    errors = sum(r.errors for r in results)
    skipped = sum(r.skipped for r in results)
    print(LINE)
    print("Ran %d test%s in %.3fs" % (ran, "" if ran == 1 else "s", elapsed))
    print()
    print(verdict_line(failures, errors, skipped))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
