"""scripts/session-check.ps1: silent when the environment is fine, a
user-visible warning plus a Claude-facing hint when it is not.

The script is copied into a scratch ``.claude/gatekit/scripts`` tree and run
with Windows PowerShell 5.1 (the one every Windows has) with a PATH that holds
only the fake ``uv``/``claude`` executables the test chooses to provide.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

KIT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = KIT / "scripts" / "session-check.ps1"
POWERSHELL = pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) / \
    "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


class TestSessionCheck(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)
        self.scripts = self.root / ".claude" / "gatekit" / "scripts"
        self.scripts.mkdir(parents=True)
        shutil.copy(SCRIPT, self.scripts / "session-check.ps1")
        self.bin = self.root / "bin"
        self.bin.mkdir()

    def fake(self, name: str) -> None:
        (self.bin / (name + ".exe")).write_bytes(b"")

    def venv(self) -> None:
        py = self.root / ".claude" / "gatekit" / ".venv" / "Scripts" / "python.exe"
        py.parent.mkdir(parents=True)
        py.write_bytes(b"MZ")  # a non-empty file: a 0 byte python.exe is a damaged venv

    def run_check(self, **extra_env):
        env = {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
               "PATH": str(self.bin), "PATHEXT": ".EXE;.CMD"}
        env.update(extra_env)
        return subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(self.scripts / "session-check.ps1")],
            capture_output=True, env=env, timeout=60)

    def test_script_exists_and_targets_windows_powershell_5(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        for banned in ("&&", "||", "?:", "??"):
            self.assertNotIn(banned, text)
        self.assertNotIn("uv sync", text.replace("`uv sync`", ""))

    def test_everything_present_prints_nothing(self) -> None:
        self.fake("uv")
        self.fake("claude")
        self.venv()
        proc = self.run_check()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), b"")

    def test_missing_venv_warns_user_and_tells_claude_to_run_setup(self) -> None:
        self.fake("uv")
        self.fake("claude")
        proc = self.run_check()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout.decode("ascii"))  # pure ASCII (\u escapes)
        self.assertIn(".venv", data["systemMessage"])
        self.assertIn("/gatekit:setup", data["systemMessage"])
        self.assertIn("환경", data["systemMessage"])  # Korean survives the \u escape
        hook = data["hookSpecificOutput"]
        self.assertEqual(hook["hookEventName"], "SessionStart")
        self.assertIn("/gatekit:setup", hook["additionalContext"])

    def test_missing_uv_and_claude_are_both_reported(self) -> None:
        self.venv()
        proc = self.run_check()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        message = json.loads(proc.stdout.decode("ascii"))["systemMessage"]
        self.assertIn("uv:", message)
        self.assertIn("claude CLI", message)
        self.assertNotIn(".venv", message)

    def test_venv_whose_python_home_is_gone_is_reported(self) -> None:
        self.fake("uv")
        self.fake("claude")
        self.venv()
        cfg = self.root / ".claude" / "gatekit" / ".venv" / "pyvenv.cfg"
        cfg.write_text("home = %s" % (self.root / "no-such-python"), encoding="utf-8")
        proc = self.run_check()
        message = json.loads(proc.stdout.decode("ascii"))["systemMessage"]
        self.assertIn("pyvenv.cfg", message)
        self.assertIn("/gatekit:setup", message)

    def test_venv_with_an_existing_python_home_is_silent(self) -> None:
        self.fake("uv")
        self.fake("claude")
        self.venv()
        cfg = self.root / ".claude" / "gatekit" / ".venv" / "pyvenv.cfg"
        cfg.write_text("home = %s" % self.root, encoding="utf-8")
        self.assertEqual(self.run_check().stdout.strip(), b"")

    def test_venv_with_a_zero_byte_python_is_reported_as_damaged(self) -> None:
        self.fake("uv")
        self.fake("claude")
        self.venv()
        py = self.root / ".claude" / "gatekit" / ".venv" / "Scripts" / "python.exe"
        py.write_bytes(b"")
        message = json.loads(self.run_check().stdout.decode("ascii"))["systemMessage"]
        self.assertIn("0 bytes", message)
        self.assertIn("/gatekit:setup", message)

    def test_program_visible_only_in_the_registry_path_says_restart_not_missing(self) -> None:
        # Same rule as setup.ps1: judged by this session's PATH; the registry only
        # tells "not installed" apart from "installed but not visible".
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "uv.exe").write_bytes(b"")
        self.fake("claude")
        self.venv()
        proc = self.run_check(GATEKIT_SETUP_REGISTRY_PATH=str(elsewhere))
        message = json.loads(proc.stdout.decode("ascii"))["systemMessage"]
        self.assertIn("uv: installed but not visible", message)
        self.assertNotIn("not found", message)
        self.assertIn("다시 여세요", message)

    def test_program_missing_everywhere_is_still_not_found(self) -> None:
        self.fake("claude")
        self.venv()
        proc = self.run_check(GATEKIT_SETUP_REGISTRY_PATH=str(self.root / "empty"))
        self.assertIn("uv: not found", json.loads(proc.stdout.decode("ascii"))["systemMessage"])

    def test_check_finishes_well_under_ten_seconds_and_never_calls_winget(self) -> None:
        import time
        text = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertNotIn("winget ", text.replace("or winget", "").replace("no winget", ""))
        started = time.monotonic()
        self.run_check()
        self.assertLess(time.monotonic() - started, 10)

    def test_check_never_creates_a_venv(self) -> None:
        self.fake("uv")
        self.fake("claude")
        self.run_check()
        self.assertFalse((self.root / ".claude" / "gatekit" / ".venv").exists())


if __name__ == "__main__":
    unittest.main()
