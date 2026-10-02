"""scripts/session-check.ps1: silent when the environment is fine, a
user-visible warning plus a Claude-facing hint when it is not.

The script is copied into a scratch ``.claude/gatekit/scripts`` tree and run
with Windows PowerShell 5.1 (the one every Windows has) with a PATH that holds
only the fake executables (``uv``, ``pwsh``) the test chooses to provide.
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
COMMON = KIT / "scripts" / "common.ps1"  # the PATH rule and the ASCII JSON, shared with setup.ps1
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
        shutil.copy(COMMON, self.scripts / "common.ps1")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.fake("pwsh")  # required like uv; one test removes it

    def fake(self, name: str) -> None:
        (self.bin / (name + ".exe")).write_bytes(b"")

    def venv(self) -> None:
        py = self.root / ".claude" / "gatekit" / ".venv" / "Scripts" / "python.exe"
        py.parent.mkdir(parents=True)
        py.write_bytes(b"MZ")  # a non-empty file: a 0 byte python.exe is a damaged venv

    def run_check(self, **extra_env):
        # The PowerShell 7 package lookup answers "none" unless a test says otherwise, so the
        # result does not depend on what this machine has installed.
        env = {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
               "PATH": str(self.bin), "PATHEXT": ".EXE;.CMD",
               "GATEKIT_SETUP_PWSH_PACKAGES": "none"}
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
        self.venv()
        proc = self.run_check()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), b"")

    def test_missing_venv_warns_user_and_tells_claude_to_run_setup(self) -> None:
        self.fake("uv")
        proc = self.run_check()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout.decode("ascii"))  # pure ASCII (\u escapes)
        self.assertIn(".venv", data["systemMessage"])
        self.assertIn("/gatekit-setup", data["systemMessage"])
        self.assertIn("환경", data["systemMessage"])  # Korean survives the \u escape
        hook = data["hookSpecificOutput"]
        self.assertEqual(hook["hookEventName"], "SessionStart")
        self.assertIn("/gatekit-setup", hook["additionalContext"])

    def config(self, data: dict) -> None:
        state = self.root / ".gatekit"
        state.mkdir(exist_ok=True)
        (state / "config.json").write_text(json.dumps(data), encoding="utf-8")

    def test_a_missing_claude_command_is_never_reported(self) -> None:
        # gatekit starts no claude process: a PC with only the desktop app or the VS Code
        # extension is fine, and settings an older kit wrote (a worker build, a backend
        # reviewer) are read by nothing.
        self.fake("uv")
        self.venv()
        for data in (None, {}, {"build": {"execution": "worker"}}, {"verify": {"evaluator": "claude"}}):
            with self.subTest(config=data):
                if data is not None:
                    self.config(data)
                proc = self.run_check(GATEKIT_SETUP_KEEP_PATH="1")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout.strip(), b"")

    def test_venv_whose_python_home_is_gone_is_reported(self) -> None:
        self.fake("uv")
        self.venv()
        cfg = self.root / ".claude" / "gatekit" / ".venv" / "pyvenv.cfg"
        cfg.write_text("home = %s" % (self.root / "no-such-python"), encoding="utf-8")
        proc = self.run_check()
        message = json.loads(proc.stdout.decode("ascii"))["systemMessage"]
        self.assertIn("pyvenv.cfg", message)
        self.assertIn("/gatekit-setup", message)

    def test_venv_with_an_existing_python_home_is_silent(self) -> None:
        self.fake("uv")
        self.venv()
        cfg = self.root / ".claude" / "gatekit" / ".venv" / "pyvenv.cfg"
        cfg.write_text("home = %s" % self.root, encoding="utf-8")
        self.assertEqual(self.run_check().stdout.strip(), b"")

    def test_minimum_python_comes_from_packages_json(self) -> None:
        self.fake("uv")
        self.venv()
        (self.scripts / "packages.json").write_text('{"python_min": "3.99"}', encoding="utf-8")
        cfg = self.root / ".claude" / "gatekit" / ".venv" / "pyvenv.cfg"
        cfg.write_text("home = %s\nversion_info = 3.14.3\n" % self.root, encoding="utf-8")
        message = json.loads(self.run_check().stdout.decode("ascii"))["systemMessage"]
        self.assertIn("3.99", message)

    def test_venv_python_below_3_14_is_reported(self) -> None:
        self.fake("uv")
        self.venv()
        cfg = self.root / ".claude" / "gatekit" / ".venv" / "pyvenv.cfg"
        for old in ("3.11.9", "3.13.5"):
            cfg.write_text("home = %s\nversion_info = %s\n" % (self.root, old), encoding="utf-8")
            message = json.loads(self.run_check().stdout.decode("ascii"))["systemMessage"]
            self.assertIn("3.14", message)
            self.assertIn("/gatekit-setup", message)
        for fine in ("3.14.3", "3.15.0"):
            cfg.write_text("home = %s\nversion_info = %s\n" % (self.root, fine), encoding="utf-8")
            self.assertEqual(self.run_check().stdout.strip(), b"")

    def test_venv_with_a_zero_byte_python_is_reported_as_damaged(self) -> None:
        self.fake("uv")
        self.venv()
        py = self.root / ".claude" / "gatekit" / ".venv" / "Scripts" / "python.exe"
        py.write_bytes(b"")
        message = json.loads(self.run_check().stdout.decode("ascii"))["systemMessage"]
        self.assertIn("0 bytes", message)
        self.assertIn("/gatekit-setup", message)

    def test_missing_powershell_7_is_reported(self) -> None:
        (self.bin / "pwsh.exe").unlink()
        self.fake("uv")
        self.venv()
        empty = self.root / "empty"  # stands in for the registry PATH: this machine's own pwsh must not count
        empty.mkdir()
        proc = self.run_check(GATEKIT_SETUP_REGISTRY_PATH=str(empty))
        message = json.loads(proc.stdout.decode("ascii"))["systemMessage"]
        self.assertIn("PowerShell 7 (pwsh): not found", message)
        self.assertIn("/gatekit-setup", message)

    # ---- PowerShell 7: the stable product, not just a pwsh on PATH (same rule as setup.ps1) ----
    STABLE = "Microsoft.PowerShell=7.6.6.0"
    PREVIEW = "Microsoft.PowerShellPreview=7.7.5.0"
    PREVIEW_ONLY = "PowerShell 7: only a preview build is installed"

    def ready(self) -> None:
        """Everything else is fine, and packages.json (the package names) is in place."""
        self.fake("uv")
        self.venv()
        shutil.copy(KIT / "scripts" / "packages.json", self.scripts / "packages.json")

    def test_preview_package_alone_is_reported(self) -> None:
        self.ready()
        proc = self.run_check(GATEKIT_SETUP_PWSH_PACKAGES=self.PREVIEW)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout.decode("ascii"))
        self.assertIn(self.PREVIEW_ONLY, data["systemMessage"])
        self.assertIn("안정판이 없습니다", data["systemMessage"])
        self.assertIn("/gatekit-setup", data["hookSpecificOutput"]["additionalContext"])

    def test_stable_package_is_silent_even_next_to_a_preview(self) -> None:
        self.ready()
        for packages in (self.STABLE, self.STABLE + ";" + self.PREVIEW):
            self.assertEqual(self.run_check(GATEKIT_SETUP_PWSH_PACKAGES=packages).stdout.strip(), b"")

    def test_preview_folder_on_path_is_reported_without_a_package(self) -> None:
        self.ready()
        (self.bin / "pwsh.exe").unlink()
        preview = self.root / "PowerShell" / "7-preview"
        preview.mkdir(parents=True)
        (preview / "pwsh.exe").write_bytes(b"")
        proc = self.run_check(PATH="%s;%s" % (self.bin, preview))
        self.assertIn(self.PREVIEW_ONLY, json.loads(proc.stdout.decode("ascii"))["systemMessage"])

    def test_stable_msi_folder_is_silent_next_to_a_preview_package(self) -> None:
        self.ready()
        stable = self.root / "Program Files" / "PowerShell" / "7"
        stable.mkdir(parents=True)
        (stable / "pwsh.exe").write_bytes(b"")
        proc = self.run_check(GATEKIT_SETUP_PWSH_PACKAGES=self.PREVIEW,
                              ProgramFiles=str(self.root / "Program Files"))
        self.assertEqual(proc.stdout.strip(), b"")

    def test_a_pwsh_of_unknown_kind_is_not_reported(self) -> None:
        # No package, no MSI folder, a pwsh.exe without version text: nothing can tell, so silent.
        self.ready()
        self.assertEqual(self.run_check().stdout.strip(), b"")

    def test_without_packages_json_the_package_lookup_is_skipped(self) -> None:
        self.fake("uv")
        self.venv()
        self.assertEqual(self.run_check(GATEKIT_SETUP_PWSH_PACKAGES=self.PREVIEW).stdout.strip(), b"")

    def test_the_real_package_lookup_stays_inside_the_time_budget(self) -> None:
        # An empty value counts as not set: Get-AppxPackage really runs (read-only, no network).
        import time
        self.ready()
        started = time.monotonic()
        proc = self.run_check(GATEKIT_SETUP_PWSH_PACKAGES="")
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_no_process_is_started_and_the_rule_comes_from_common_ps1(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8-sig")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        for banned in ("Start-Process", "Invoke-Proc", "Process]::Start", "Invoke-Expression", "& $"):
            self.assertNotIn(banned, code)
        self.assertIn("Get-PwshProduct $pwshStableName $pwshPreviewName", code)
        self.assertNotIn("Get-AppxPackage", code)  # only inside common.ps1

    def test_program_visible_only_in_the_registry_path_says_restart_not_missing(self) -> None:
        # Same rule as setup.ps1: judged by this session's PATH; the registry only
        # tells "not installed" apart from "installed but not visible".
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "uv.exe").write_bytes(b"")
        self.venv()
        proc = self.run_check(GATEKIT_SETUP_REGISTRY_PATH=str(elsewhere))
        message = json.loads(proc.stdout.decode("ascii"))["systemMessage"]
        self.assertIn("uv: installed but not visible", message)
        self.assertNotIn("not found", message)
        self.assertIn("다시 여세요", message)

    #: Closing the window of the desktop app leaves it running: the reopen advice says where to quit it.
    TRAY_EN = "quit it from the Claude icon in the notification area (bottom right of the taskbar)"
    TRAY_KO = "작업 표시줄 오른쪽 아래(트레이)의 Claude 아이콘에서 종료하세요"

    def test_reopen_advice_names_the_tray_icon_once(self) -> None:
        # Two programs need a reopen: the environment-neutral sentence stays on each line and the
        # tray note follows the list once, for the user and for Claude.
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "uv.exe").write_bytes(b"")
        (elsewhere / "pwsh.exe").write_bytes(b"")
        (self.bin / "pwsh.exe").unlink()
        self.venv()
        data = json.loads(self.run_check(GATEKIT_SETUP_REGISTRY_PATH=str(elsewhere)).stdout.decode("ascii"))
        message = data["systemMessage"]
        reopen = ("close Claude Code completely (the desktop app, the VS Code window, "
                  "or the terminal it runs in) and open it again")
        self.assertEqual(message.count(reopen), 2, message)
        self.assertEqual(message.count("완전히 닫고 다시 여세요"), 2, message)
        for text in (message, data["hookSpecificOutput"]["additionalContext"]):
            self.assertEqual(text.count(self.TRAY_EN), 1, text)
            self.assertEqual(text.count(self.TRAY_KO), 1, text)
        self.assertLess(message.rindex(reopen), message.index(self.TRAY_EN))

    def test_program_missing_everywhere_is_still_not_found(self) -> None:
        self.venv()
        proc = self.run_check(GATEKIT_SETUP_REGISTRY_PATH=str(self.root / "empty"))
        message = json.loads(proc.stdout.decode("ascii"))["systemMessage"]
        self.assertIn("uv: not found", message)
        self.assertNotIn(self.TRAY_EN, message)  # nothing to reopen: no tray note
        self.assertNotIn("트레이", message)

    def test_check_finishes_well_under_ten_seconds_and_never_calls_winget(self) -> None:
        import time
        text = SCRIPT.read_text(encoding="utf-8-sig")
        self.assertNotIn("winget ", text.replace("or winget", "").replace("no winget", ""))
        started = time.monotonic()
        self.run_check()
        self.assertLess(time.monotonic() - started, 10)

    def test_check_never_creates_a_venv(self) -> None:
        self.fake("uv")
        self.run_check()
        self.assertFalse((self.root / ".claude" / "gatekit" / ".venv").exists())


if __name__ == "__main__":
    unittest.main()
