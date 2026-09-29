"""`gatekit.py setup`: arguments go to scripts/setup.ps1 unchanged, its output and its
exit code come back unchanged."""
from __future__ import annotations

import io
import contextlib
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from gatekit import cli, paths, setup as setup_cli
from tests import fakebin
from tests.test_scripts import POWERSHELL

KIT = pathlib.Path(__file__).resolve().parents[1]
LAUNCHER = KIT / "bin" / "gatekit.py"


def parse(argv):
    return setup_cli._parser().parse_args(argv)


class TestBuildCommand(unittest.TestCase):
    def command(self, argv):
        return setup_cli.build_command("PS.exe", pathlib.Path("S.ps1"), parse(argv))

    def test_fixed_prefix_is_noprofile_bypass_file(self) -> None:
        self.assertEqual(self.command([]),
                         ["PS.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "S.ps1"])

    def test_every_option_is_forwarded(self) -> None:
        got = self.command(["--install", "uv,claude", "--update", "pwsh", "--reinstall", "uv",
                            "--retry-failed", "--status", "--json", "--lang", "ko"])
        self.assertEqual(got[6:], ["-Install", "uv,claude", "-Update", "pwsh", "-Reinstall", "uv",
                                   "-RetryFailed", "-Status", "-Json", "-Lang", "ko"])

    def test_repeated_option_is_joined_with_commas(self) -> None:
        got = self.command(["--install", "uv", "--install", "venv"])
        self.assertEqual(got[6:], ["-Install", "uv,venv"])

    def test_names_are_not_judged_here(self) -> None:
        got = self.command(["--reinstall", "git,foo"])
        self.assertEqual(got[6:], ["-Reinstall", "git,foo"])  # the script refuses them


class TestRun(unittest.TestCase):
    def run_with(self, argv, code=0):
        seen = {}

        def fake_run(command, **kwargs):
            seen["command"] = command
            seen["kwargs"] = kwargs
            return subprocess.CompletedProcess(command, code)

        with mock.patch.object(setup_cli.subprocess, "run", fake_run), \
                mock.patch.object(setup_cli, "powershell_path", lambda: "PS.exe"):
            result = setup_cli.run(argv)
        return result, seen

    def test_exit_codes_pass_through(self) -> None:
        for code in (0, 1, 2, 3, 4):
            result, seen = self.run_with(["--json"], code)
            self.assertEqual(result, code)
        self.assertIn("-Json", seen["command"])

    def test_output_is_inherited_not_captured(self) -> None:
        _, seen = self.run_with([])
        self.assertNotIn("capture_output", seen["kwargs"])
        self.assertNotIn("stdout", seen["kwargs"])
        self.assertNotIn("shell", seen["kwargs"])
        self.assertEqual(seen["command"][0], "PS.exe")

    def test_script_is_the_kits_own_setup_ps1(self) -> None:
        _, seen = self.run_with([])
        self.assertEqual(pathlib.Path(seen["command"][5]), paths.gatekit_root() / "scripts" / "setup.ps1")
        self.assertTrue(pathlib.Path(seen["command"][5]).is_file())

    def test_bad_arguments_exit_1_not_2(self) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(setup_cli.run(["--lang", "fr"]), 1)
            self.assertEqual(setup_cli.run(["--nope"]), 1)
        self.assertIn("usage", err.getvalue())

    def test_help_exits_0(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(setup_cli.run(["--help"]), 0)
        self.assertIn("--reinstall", out.getvalue())
        self.assertIn("scripts/setup.ps1", out.getvalue())

    def test_registered_in_the_cli(self) -> None:
        self.assertIn("setup", cli.SUBCOMMANDS)
        self.assertEqual(cli.SUBCOMMANDS["setup"][0], "gatekit.setup")
        self.assertIn("--reinstall", cli.SUBCOMMANDS["setup"][1])


class TestEndToEnd(unittest.TestCase):
    """A child process, so that the inherited stdout is really the child's stdout."""

    def child(self, ps_exe, *argv):
        code = ("import sys; sys.path.insert(0, %r); from gatekit import setup; "
                "setup.powershell_path = lambda: %r; sys.exit(setup.run(%r))"
                % (str(KIT), str(ps_exe), list(argv)))
        env = dict(os.environ, PYTHONUTF8="1")
        return subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, timeout=60)

    def test_fake_powershell_output_and_exit_code_come_back_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = ("import sys\n"
                   "sys.stdout.buffer.write(('한글 출력 ' + ' '.join(sys.argv[1:]) + chr(10)).encode('utf-8'))\n"
                   "sys.stderr.write('warn line' + chr(10))\n"
                   "sys.exit(3)\n")
            shim = fakebin.make_fake(tmp, "fake-powershell", src)
            proc = self.child(shim, "--install", "uv", "--lang", "ko")
        self.assertEqual(proc.returncode, 3)
        out = proc.stdout.decode("utf-8")
        self.assertIn("한글 출력 -NoProfile -ExecutionPolicy Bypass -File", out)
        self.assertIn("-Install uv -Lang ko", out)
        self.assertIn("warn line", proc.stderr.decode("utf-8", "replace"))

    @unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
    def test_real_script_refusal_comes_back_as_exit_1(self) -> None:
        # The script refuses the name before it does anything, so nothing is touched.
        proc = subprocess.run([sys.executable, str(LAUNCHER), "setup", "--reinstall", "foo", "--lang", "en"],
                              capture_output=True, timeout=120)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("refused", proc.stdout.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
