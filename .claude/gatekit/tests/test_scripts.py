"""scripts/*.ps1 must stay Windows PowerShell 5.1 compatible, and setup.ps1
must behave as documented: check-only by default, install only what was
allowed, refuse unknown names, and report through the documented exit codes.

Nothing here installs anything. Programs are replaced by fake executables that
log their arguments (a fake ``winget``, a fake ``uv``), and setup.ps1 runs from
a scratch copy of the kit with a PATH that holds only those fakes.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from tests import fakebin

KIT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = KIT.parents[1]
SCRIPTS = KIT / "scripts"
POWERSHELL = pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) / \
    "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"

PARSE_SNIPPET = (
    "$e = $null; $t = $null; "
    "[void][System.Management.Automation.Language.Parser]::ParseFile("
    "$env:GK_FILE, [ref]$t, [ref]$e); "
    "if ($e.Count -gt 0) { $e | ForEach-Object { $_.Message + ' @' + $_.Extent.StartLineNumber }; exit 1 }")


class TestScriptFiles(unittest.TestCase):
    def test_expected_scripts_exist(self) -> None:
        for name in ("session-check.ps1", "setup.ps1", "verify.ps1"):
            self.assertTrue((SCRIPTS / name).is_file(), name)

    def test_every_script_has_a_utf8_bom(self) -> None:
        # Windows PowerShell 5.1 decodes BOM-less files as the ANSI code page,
        # which would mangle the Korean messages.
        for path in sorted(SCRIPTS.glob("*.ps1")):
            self.assertEqual(path.read_bytes()[:3], b"\xef\xbb\xbf", "%s needs a UTF-8 BOM" % path.name)

    def test_powershell_7_only_syntax_is_absent(self) -> None:
        for path in sorted(SCRIPTS.glob("*.ps1")):
            text = path.read_bytes().decode("utf-8-sig")
            for banned in ("&&", "||", "?:", "??", "?."):
                self.assertNotIn(banned, text, "%s uses %r (PowerShell 7 only)" % (path.name, banned))

    @unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
    def test_every_script_parses_in_windows_powershell_5_1(self) -> None:
        for path in sorted(SCRIPTS.glob("*.ps1")):
            env = dict(os.environ, GK_FILE=str(path))
            proc = subprocess.run(
                [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PARSE_SNIPPET],
                capture_output=True, env=env, timeout=60)
            self.assertEqual(proc.returncode, 0, "%s: %s" % (
                path.name, proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")))

    def test_no_interactive_prompt_in_scripts(self) -> None:
        for path in sorted(SCRIPTS.glob("*.ps1")):
            text = path.read_bytes().decode("utf-8-sig")
            for line in text.splitlines():
                if line.lstrip().startswith("#"):
                    continue
                self.assertNotIn("Read-Host", line, path.name)

    def test_gitattributes_pins_ps1_line_endings(self) -> None:
        text = (PROJECT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.ps1 text eol=crlf", text.splitlines())

    def test_setup_command_asks_with_one_question_and_does_not_auto_approve_it(self) -> None:
        text = (PROJECT / ".claude" / "commands" / "gatekit" / "setup.md").read_text(encoding="utf-8")
        front = text.split("---")[1]
        allowed = [line for line in front.splitlines() if line.startswith("allowed-tools:")]
        self.assertEqual(len(allowed), 1)
        self.assertNotIn("AskUserQuestion", allowed[0])
        self.assertIn("AskUserQuestion", text.split("---", 2)[2])
        self.assertIn("-Install", text)


def base_env(bin_dir: pathlib.Path, local_app: pathlib.Path) -> dict:
    """A scratch environment: only the fakes on PATH, no inherited policy
    override (PSExecutionPolicyPreference is deliberately absent)."""
    return {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
            "PATH": str(bin_dir), "PATHEXT": ".EXE;.CMD",
            "LOCALAPPDATA": str(local_app),
            "GATEKIT_SETUP_KEEP_PATH": "1"}


class SetupCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)
        self.kit = self.root / ".claude" / "gatekit"
        (self.kit / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPTS / "setup.ps1", self.kit / "scripts" / "setup.ps1")
        shutil.copy(PROJECT / ".claude" / "settings.json", self.root / ".claude" / "settings.json")
        self.bin = self.root / "fakebin"
        self.bin.mkdir()
        self.local = self.root / "local"
        self.local.mkdir()
        self.log = self.root / "calls.log"

    def fake_uv(self) -> None:
        src = ("import sys\n"
               "open(%r, 'a').write('uv ' + ' '.join(sys.argv[1:]) + chr(10))\n"
               "print('uv 0.10.7 (fake)')\n" % str(self.log))
        fakebin.make_fake(self.bin, "uv", src)

    def fake_winget(self, install_code: int) -> None:
        src = ("import sys\n"
               "open(%r, 'a').write('winget ' + ' '.join(sys.argv[1:]) + chr(10))\n"
               "if sys.argv[1] == '--version':\n"
               "    print('v1.29.380'); sys.exit(0)\n"
               "if sys.argv[1] == 'search':\n"
               "    print('astral-sh.uv'); sys.exit(0)\n"
               "sys.exit(%d)\n" % (str(self.log), install_code))
        fakebin.make_fake(self.bin, "winget", src)

    def calls(self) -> list:
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def run_setup(self, *args: str):
        proc = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(self.kit / "scripts" / "setup.ps1"), *args],
            capture_output=True, env=base_env(self.bin, self.local), timeout=180)
        return proc.returncode, proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupWithoutUv(SetupCase):
    def test_missing_uv_prints_install_commands_and_exits_2(self) -> None:
        code, out = self.run_setup()
        self.assertEqual(code, 2, out)
        self.assertIn("winget install --id=astral-sh.uv -e", out)
        self.assertIn("https://astral.sh/uv/install.ps1", out)
        self.assertIn("[fail]", out)
        self.assertIn("-Install uv", out)

    def test_check_only_never_installs_or_accepts_agreements(self) -> None:
        self.fake_winget(0)
        code, out = self.run_setup()
        self.assertEqual(code, 2, out)
        self.assertTrue(self.calls())
        for call in self.calls():
            self.assertNotIn(" install ", " " + call + " ")
            self.assertNotIn("--accept", call)
            if not call.endswith("--version"):
                self.assertIn("--disable-interactivity", call)

    def test_unknown_name_is_refused_with_exit_1(self) -> None:
        self.fake_winget(0)
        code, out = self.run_setup("-Install", "foo,uv")
        self.assertEqual(code, 1, out)
        self.assertIn('"foo"', out)
        self.assertEqual([c for c in self.calls() if " install " in c], [])
        code, out = self.run_setup("-Update", "rm")
        self.assertEqual(code, 1, out)

    def test_bad_language_is_refused(self) -> None:
        code, out = self.run_setup("-Lang", "fr")
        self.assertEqual(code, 1, out)

    def test_json_schema(self) -> None:
        code, out = self.run_setup("-Json", "-Lang", "en")
        data = json.loads(out)
        self.assertEqual(data["exit_code"], code)
        self.assertEqual(code, 2)
        self.assertTrue(data["items"])
        for item in data["items"]:
            for key in ("id", "level", "verdict", "detail", "action"):
                self.assertIn(key, item)
            self.assertIn(item["verdict"], ("ok", "warn", "fail", "unverified", "info"))
            self.assertIn(item["level"], ("required", "recommended", "info"))
        by_id = {i["id"]: i for i in data["items"]}
        self.assertEqual(by_id["S4"]["verdict"], "fail")
        self.assertEqual(by_id["S5"]["verdict"], "unverified")  # not checked, not passed

    def test_lang_ko_prints_korean_only(self) -> None:
        _, out = self.run_setup("-Lang", "ko")
        self.assertIn("uv 를 찾을 수 없습니다", out)
        self.assertNotIn("uv not found", out)


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupInstallPaths(SetupCase):
    def install_calls(self) -> list:
        return [c for c in self.calls() if c.startswith("winget install")]

    def test_allowed_install_passes_agreement_flags_and_disables_interactivity(self) -> None:
        self.fake_winget(0)
        code, out = self.run_setup("-Install", "uv")
        calls = self.install_calls()
        self.assertEqual(len(calls), 1, self.calls())
        self.assertIn("--id astral-sh.uv", calls[0])
        self.assertIn("--disable-interactivity", calls[0])
        self.assertIn("--accept-source-agreements", calls[0])
        self.assertIn("--accept-package-agreements", calls[0])
        # winget "succeeded" but nothing appeared on PATH: restart needed (S9).
        self.assertEqual(code, 3, out)
        self.assertIn("PATH", out)

    def test_pwsh_uses_the_microsoft_powershell_id(self) -> None:
        self.fake_winget(0)
        self.run_setup("-Install", "pwsh")
        calls = self.install_calls()
        self.assertEqual(len(calls), 1, self.calls())
        self.assertIn("--id Microsoft.PowerShell -e --source winget", calls[0])

    def test_policy_block_exits_4_with_a_message_for_it(self) -> None:
        self.fake_winget(0x8A15003A)
        code, out = self.run_setup("-Install", "uv", "-Lang", "en")
        self.assertEqual(code, 4, out)
        self.assertIn("policy", out)
        self.assertIn("What you can do now", out)
        self.assertIn("Message for your IT contact", out)

    def test_network_failure_exits_4(self) -> None:
        self.fake_winget(0x8A150107)
        code, out = self.run_setup("-Install", "uv", "-Lang", "en")
        self.assertEqual(code, 4, out)
        self.assertIn("network", out)

    def test_unaccepted_agreement_needs_the_user_exit_2(self) -> None:
        self.fake_winget(0x8A150046)
        code, out = self.run_setup("-Install", "uv", "-Lang", "en")
        self.assertEqual(code, 2, out)
        self.assertIn("agreements", out)

    def test_unknown_winget_failure_is_exit_1(self) -> None:
        self.fake_winget(0x8A150999)
        code, out = self.run_setup("-Install", "uv", "-Lang", "en")
        self.assertEqual(code, 1, out)
        self.assertIn("0x8A150999", out)

    def test_git_is_never_installed_automatically(self) -> None:
        self.fake_winget(0)
        code, out = self.run_setup("-Install", "git", "-Lang", "en")
        self.assertEqual(self.install_calls(), [])
        self.assertIn("winget install --id Git.Git", out)  # printed as guidance only
        self.assertIn("administrator", out)

    def test_already_installed_program_is_skipped(self) -> None:
        self.fake_uv()
        self.fake_winget(0)
        self.run_setup("-Install", "uv")
        self.assertEqual(self.install_calls(), [])


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupVenv(SetupCase):
    def test_venv_whose_python_home_is_gone_is_recreated(self) -> None:
        self.fake_uv()
        venv = self.kit / ".venv"
        (venv / "Scripts").mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text(
            "home = %s\nversion_info = 3.14.3\n" % (self.root / "no-such-python"), encoding="utf-8")
        (venv / "Scripts" / "python.exe").write_bytes(b"")
        code, out = self.run_setup("-Lang", "en")
        self.assertIn("Deleting the broken .venv", out)
        self.assertFalse((venv / "pyvenv.cfg").exists(), out)  # removed; the fake uv builds nothing
        self.assertTrue(any(c.startswith("uv sync") and "--frozen" in c for c in self.calls()), self.calls())

    def test_venv_with_an_existing_home_is_left_alone(self) -> None:
        self.fake_uv()
        venv = self.kit / ".venv"
        (venv / "Scripts").mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = %s\n" % self.root, encoding="utf-8")
        (venv / "Scripts" / "python.exe").write_bytes(b"")
        self.run_setup("-Lang", "en")
        self.assertTrue((venv / "pyvenv.cfg").exists())


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupExecutionPolicy(SetupCase):
    def test_runs_without_a_process_policy_override(self) -> None:
        # PSExecutionPolicyPreference can mask an execution-policy block; the
        # scratch environment has none, and the invocation carries its own
        # -ExecutionPolicy Bypass, so the script must still run.
        self.assertNotIn("PSExecutionPolicyPreference", base_env(self.bin, self.local))
        code, out = self.run_setup("-Lang", "en")
        self.assertEqual(code, 2, out)
        self.assertNotIn("cannot be loaded", out)


if __name__ == "__main__":
    unittest.main()
