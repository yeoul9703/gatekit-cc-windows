"""scripts/*.ps1 must stay Windows PowerShell 5.1 compatible, and setup.ps1
must behave as documented: check-only by default, install only what was
allowed, refuse unknown names, and report through the documented exit codes.
(What the setup skill's documents say is checked in test_command_docs.py.)

Nothing here installs anything. Programs are replaced by fake executables that
log their arguments (a fake ``winget``, a fake ``uv``), and setup.ps1 runs from
a scratch copy of the kit with a PATH that holds only those fakes.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
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
        for name in ("common.ps1", "session-check.ps1", "setup.ps1", "verify.ps1"):
            self.assertTrue((SCRIPTS / name).is_file(), name)

    def test_common_ps1_is_in_the_bom_and_syntax_checks(self) -> None:
        # The BOM, PowerShell 7 syntax, Read-Host and 5.1 parse checks all walk SCRIPTS.glob("*.ps1"):
        # the shared file must be part of that walk, and it must start with the one-line summary.
        self.assertIn("common.ps1", [path.name for path in SCRIPTS.glob("*.ps1")])
        raw = (SCRIPTS / "common.ps1").read_bytes()
        self.assertEqual(raw[:3], b"\xef\xbb\xbf")
        first = raw.decode("utf-8-sig").splitlines()[0]
        self.assertTrue(first.startswith("# common.ps1"), first)

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


def base_env(bin_dir: pathlib.Path, local_app: pathlib.Path) -> dict:
    """A scratch environment: only the fakes on PATH, no inherited policy
    override (PSExecutionPolicyPreference is deliberately absent). The PowerShell 7
    package lookup answers "none" (an empty value would count as not set and ask this
    machine), and without ProgramFiles the MSI folder is not looked at either. The group
    policy execution policy and the long-path registry value are pinned too, so a test does
    not depend on how this machine is configured."""
    return {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
            "PATH": str(bin_dir), "PATHEXT": ".EXE;.CMD",
            "LOCALAPPDATA": str(local_app),
            "GATEKIT_SETUP_KEEP_PATH": "1",
            "GATEKIT_SETUP_PWSH_PACKAGES": "none",
            "GATEKIT_SETUP_EXECUTION_POLICY": "MachinePolicy=Undefined;UserPolicy=Undefined",
            "GATEKIT_SETUP_LONG_PATHS": "0"}


#: Program and product names that may appear inside a Korean line.
_NAMES = {"uv", "claude", "cli", "code", "git", "windows", "winget", "pwsh", "powershell", "gatekit",
          "python", "node", "npm", "microsoft", "store", "app", "installer", "onedrive", "applocker",
          "intune", "doctor", "ok", "warn", "fail", "info", "vs", "tls", "url", "mb",
          # command vocabulary (the commands themselves are printed as hints)
          "run", "sync", "contract", "derive", "spec", "validate", "self", "update", "install",
          "upgrade", "search", "workers", "check"}


def english_sentence_lines(text: str) -> list:
    """Lines with two or more consecutive plain English words that are not program
    names (an English sentence). Commands (``--flags``), paths, versions and product
    names do not count."""
    bad = []
    for line in text.splitlines():
        words = 0
        for token in line.split():
            word = token.lstrip("(\"'").rstrip(".,;:!?)\"'")
            if word in ("[ok]", "[warn]", "[fail]", "[info]", "[unverified]"):
                continue  # the verdict tag is not a sentence
            if re.fullmatch(r"[A-Za-z]{2,}", word):
                if word != "IT" and word.lower() not in _NAMES:
                    words += 1
            else:
                words = 0
            if words >= 2:
                bad.append(line)
                break
    return bad


#: Source of a fake ``uv``. MODE picks what ``uv sync`` does:
#:   plain     exit 0 and build nothing
#:   nopython  no Python on the PC: with --no-python-downloads it fails like uv does,
#:             without it it "downloads Python" and builds a working .venv
#:   build     build a working .venv
#:   fail      print TEXT, exit 1
#:   hang      write its pid to PIDFILE and sleep (to be killed by the timeout)
FAKE_UV = r'''
import glob, os, shutil, sys, time
args = sys.argv[1:]
open(LOG, 'a').write('uv ' + ' '.join(args) + chr(10))
if args[:1] != ['sync']:
    print('uv 0.10.7 (fake)')
    sys.exit(0)
mode = MODE
if mode == 'nopython' and '--no-python-downloads' in args:
    print('error: No interpreter found for Python >=3.14 in managed installations or search path')
    sys.exit(2)
if mode == 'fail':
    print(TEXT)
    sys.exit(1)
if mode == 'hang':
    open(PIDFILE, 'w').write(str(os.getpid()))
    time.sleep(120)
    sys.exit(0)
if mode in ('nopython', 'build'):
    venv = os.path.join(args[args.index('--project') + 1], '.venv')
    scripts = os.path.join(venv, 'Scripts')
    os.makedirs(scripts, exist_ok=True)
    base = sys.base_prefix
    for name in ['python.exe'] + [os.path.basename(x) for x in glob.glob(os.path.join(base, '*.dll'))]:
        shutil.copy(os.path.join(base, name), os.path.join(scripts, name))
    open(os.path.join(venv, 'pyvenv.cfg'), 'w').write('home = ' + base + chr(10) + 'version_info = 3.14.3' + chr(10))
sys.exit(0)
'''


class TestEnglishSentenceDetector(unittest.TestCase):
    def test_flags_english_sentences_but_not_commands_or_names(self) -> None:
        self.assertTrue(english_sentence_lines("[warn] uv: not found, install it yourself"))
        self.assertTrue(english_sentence_lines("[ok] git: 이미 설치되어 있습니다 already installed"))
        self.assertEqual(english_sentence_lines("[fail] uv: 설치하세요 (-Install uv)"), [])
        self.assertEqual(english_sentence_lines("       winget install --id Git.Git -e --source winget"), [])
        self.assertEqual(english_sentence_lines("[info] git: Git for Windows 가 없습니다"), [])
        self.assertEqual(english_sentence_lines("IT 담당자님, AppLocker/Intune 정책"), [])


class SetupCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)
        self.kit = self.root / ".claude" / "gatekit"
        (self.kit / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPTS / "setup.ps1", self.kit / "scripts" / "setup.ps1")
        shutil.copy(SCRIPTS / "common.ps1", self.kit / "scripts" / "common.ps1")
        shutil.copy(SCRIPTS / "packages.json", self.kit / "scripts" / "packages.json")
        shutil.copy(PROJECT / ".claude" / "settings.json", self.root / ".claude" / "settings.json")
        self.bin = self.root / "fakebin"
        self.bin.mkdir()
        self.local = self.root / "local"
        self.local.mkdir()
        self.log = self.root / "calls.log"

    def fake_uv(self, mode: str = "plain", text: str = "", pidfile: str = "") -> None:
        src = ("LOG = %r\nMODE = %r\nTEXT = %r\nPIDFILE = %r\n" % (str(self.log), mode, text, pidfile)) + FAKE_UV
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

    def fake_pwsh(self, version: str, directory: "pathlib.Path | None" = None) -> None:
        target = directory or self.bin
        target.mkdir(exist_ok=True)
        fakebin.make_fake(target, "pwsh", "print(%r)\n" % version)

    def fake_official_runner(self, code: int) -> str:
        """A stand-in for the official installer script: logs the URL, exits *code*."""
        src = ("import sys\n"
               "open(%r, 'a').write('official ' + ' '.join(sys.argv[1:]) + chr(10))\n"
               "sys.exit(%d)\n" % (str(self.log), code))
        return str(fakebin.make_fake(self.bin, "official-runner", src))

    def copy_kit_sources(self) -> None:
        """A scratch kit that can really run doctor: the package, launcher and scripts."""
        ignore = shutil.ignore_patterns("__pycache__", ".venv", "tests", "*.pyc")
        for name in ("gatekit", "bin"):
            shutil.copytree(KIT / name, self.kit / name, ignore=ignore, dirs_exist_ok=True)
        for name in ("pyproject.toml", "uv.lock"):
            shutil.copy(KIT / name, self.kit / name)
        for path in SCRIPTS.glob("*.ps1"):
            shutil.copy(path, self.kit / "scripts" / path.name)

    def calls(self) -> list:
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def sync_calls(self) -> list:
        return [c for c in self.calls() if c.startswith("uv sync")]

    def run_setup(self, *args: str, env: "dict | None" = None):
        environment = base_env(self.bin, self.local)
        environment.update(env or {})
        proc = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(self.kit / "scripts" / "setup.ps1"), *args],
            capture_output=True, env=environment, timeout=180)
        return proc.returncode, proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")

    def run_json(self, *args: str, env: "dict | None" = None):
        code, out = self.run_setup("-Json", *args, env=env)
        data = json.loads(out)
        self.assertEqual(data["exit_code"], code)
        return code, data, {i["id"]: i for i in data["items"]}


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupWithoutUv(SetupCase):
    def test_missing_uv_prints_install_commands_and_exits_2(self) -> None:
        code, out = self.run_setup("-Lang", "en")
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

    def test_venv_is_an_install_name_only(self) -> None:
        code, out = self.run_setup("-Update", "venv", "-Lang", "en")
        self.assertEqual(code, 1, out)
        self.assertIn("-Install venv", out)

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

    def test_default_language_is_one_language_not_both(self) -> None:
        _, out = self.run_setup()
        self.assertFalse("uv not found" in out and "uv 를 찾을 수 없습니다" in out, out)

    def test_lang_ko_has_no_english_sentence(self) -> None:
        for extra in ((), ("-Install", "pwsh")):
            self.fake_winget(0x8A15003A)
            _, out = self.run_setup("-Lang", "ko", *extra)
            self.assertEqual(english_sentence_lines(out), [], out)
            self.assertNotIn("원본", out)  # a mistranslation of "source"

    def test_json_is_pure_ascii_with_unicode_escapes(self) -> None:
        code, out = self.run_setup("-Json", "-Lang", "ko")
        out.encode("ascii")  # raises if any non-ASCII character is left
        self.assertIn("\\u", out)
        data = json.loads(out)
        by_id = {i["id"]: i for i in data["items"]}
        self.assertIn("uv 를 찾을 수 없습니다", by_id["S4"]["detail"])

    def test_json_records_skipped_progress_and_done_lines(self) -> None:
        self.fake_uv()
        self.fake_winget(0)
        _, _, by_id = self.run_json("-Install", "uv", "-Lang", "en")
        self.assertIn("A-uv", by_id)  # the "already installed, skipped" line
        self.assertIn("skipped", by_id["A-uv"]["detail"])
        self.assertIn("project", by_id)
        _, _, by_id = self.run_json("-Install", "pwsh", "-Lang", "en")
        self.assertIn("A-pwsh", by_id)  # the "running winget ..." progress line

    def test_settings_hook_without_noprofile_and_bypass_fails_s12(self) -> None:
        settings = json.loads((self.root / ".claude" / "settings.json").read_text(encoding="utf-8"))
        args = settings["hooks"]["SessionStart"][0]["hooks"][0]["args"]
        del args[:3]  # -NoProfile -ExecutionPolicy Bypass
        (self.root / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        code, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["S12-settings"]["verdict"], "fail", by_id["S12-settings"])
        self.assertIn("-NoProfile -ExecutionPolicy Bypass", by_id["S12-settings"]["detail"])
        self.assertEqual(code, 1)

    def test_settings_without_the_powershell_tool_env_or_default_shell_fails_s12(self) -> None:
        path = self.root / ".claude" / "settings.json"
        for drop, named in (("env", "CLAUDE_CODE_USE_POWERSHELL_TOOL"), ("defaultShell", "defaultShell")):
            with self.subTest(drop=drop):
                settings = json.loads((PROJECT / ".claude" / "settings.json").read_text(encoding="utf-8"))
                del settings[drop]
                path.write_text(json.dumps(settings), encoding="utf-8")
                code, _, by_id = self.run_json("-Lang", "en")
                self.assertEqual(by_id["S12-settings"]["verdict"], "fail", by_id["S12-settings"])
                self.assertIn(named, by_id["S12-settings"]["detail"])
                self.assertEqual(code, 2)  # the user can fix it: not exit 1

    def test_missing_powershell_7_is_a_required_fail_that_offers_the_install(self) -> None:
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["S2"]["level"], "required")
        self.assertEqual(by_id["S2"]["verdict"], "fail", by_id["S2"])
        self.assertIn("-Install winget,pwsh", by_id["S2"]["action"])  # no winget here either

    def test_real_settings_hook_flags_are_accepted(self) -> None:
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["S12-settings"]["verdict"], "ok", by_id["S12-settings"])


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

    def test_pwsh_uses_the_microsoft_powershell_id_and_msix(self) -> None:
        self.fake_winget(0)
        self.run_setup("-Install", "pwsh")
        calls = self.install_calls()
        self.assertEqual(len(calls), 1, self.calls())
        self.assertIn("--id Microsoft.PowerShell -e --source winget", calls[0])
        self.assertIn("--installer-type msix", calls[0])

    def test_policy_block_exits_4_with_a_message_for_it(self) -> None:
        self.fake_winget(0x8A15003A)
        code, out = self.run_setup("-Install", "pwsh", "-Lang", "en")
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

    def test_winget_exit_codes_map_to_the_documented_classes(self) -> None:
        # winget's documented return codes (docs: winget "return codes" table).
        expected = {
            0x8A15003A: 4,  # blocked by group policy
            0x8A15010F: 4,  # install blocked by policy
            0x8A15001B: 4,  # Store policy
            0x8A15001C: 4,  # Store policy
            0x8A150107: 4,  # download failed / network
            0x80072EFD: 4,  # TLS / server connection
            0x8A150109: 3,  # reboot required
            0x8A150046: 2,  # source agreements not accepted
            0x8A150041: 2,  # package agreements not accepted
            0x8A150999: 1,  # unknown
        }
        for winget_code, exit_code in expected.items():
            with self.subTest(code=hex(winget_code)):
                self.fake_winget(winget_code)
                code, out = self.run_setup("-Install", "pwsh", "-Lang", "en")
                self.assertEqual(code, exit_code, out)

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

    def test_update_git_passes_when_git_exists_and_never_upgrades_it(self) -> None:
        self.fake_winget(0)
        fakebin.make_fake(self.bin, "git", "print('git version 2.54.0')\n")
        _, _, by_id = self.run_json("-Update", "git", "-Lang", "en")
        self.assertNotIn("S10-git", by_id)  # no "needs administrator" warning
        self.assertEqual(by_id["A-git"]["verdict"], "ok")
        for call in self.calls():
            self.assertNotIn(" upgrade ", " " + call + " ")
            self.assertNotIn(" install ", " " + call + " ")
            if "Git.Git" in call:
                self.assertTrue(call.startswith("winget list "), call)  # a read-only lookup only

    def test_update_accepts_agreements_only_for_the_listed_program(self) -> None:
        self.fake_winget(0)
        self.fake_pwsh("7.6.0")
        self.run_setup("-Update", "pwsh", "-Lang", "en")
        upgrades = [c for c in self.calls() if c.startswith("winget upgrade")]
        self.assertEqual(len(upgrades), 1, self.calls())
        self.assertIn("--id Microsoft.PowerShell", upgrades[0])
        self.assertIn("--accept-source-agreements", upgrades[0])
        self.assertIn("--accept-package-agreements", upgrades[0])
        self.assertIn("--installer-type msix", upgrades[0])
        for call in self.calls():
            if call not in upgrades:
                self.assertNotIn("--accept", call)  # the check calls carry no agreement flag

    def test_update_of_a_missing_program_needs_an_install_first(self) -> None:
        self.fake_winget(0)
        code, _, by_id = self.run_json("-Update", "pwsh", "-Lang", "en")
        self.assertEqual(by_id["S16-pwsh"]["verdict"], "warn")
        self.assertEqual([c for c in self.calls() if c.startswith("winget upgrade")], [])

    def test_uv_policy_block_falls_back_to_the_official_script(self) -> None:
        self.fake_winget(0x8A15003A)
        runner = self.fake_official_runner(0)
        code, out = self.run_setup("-Install", "uv", "-Lang", "en",
                                   env={"GATEKIT_SETUP_OFFICIAL_RUNNER": runner})
        self.assertIn("official https://astral.sh/uv/install.ps1", self.calls())
        self.assertEqual(len(self.install_calls()), 1, self.calls())  # winget tried once first
        self.assertEqual(code, 3, out)  # the fake installed nothing on PATH: restart needed

    def test_uv_policy_block_with_a_failing_script_is_exit_4(self) -> None:
        self.fake_winget(0x8A15003A)
        runner = self.fake_official_runner(1)
        code, out = self.run_setup("-Install", "uv", "-Lang", "en",
                                   env={"GATEKIT_SETUP_OFFICIAL_RUNNER": runner})
        self.assertEqual(code, 4, out)
        self.assertIn("official https://astral.sh/uv/install.ps1", self.calls())

    def test_uv_network_failure_does_not_fall_back(self) -> None:
        self.fake_winget(0x8A150107)
        runner = self.fake_official_runner(0)
        code, out = self.run_setup("-Install", "uv", "-Lang", "en",
                                   env={"GATEKIT_SETUP_OFFICIAL_RUNNER": runner})
        self.assertEqual(code, 4, out)
        self.assertNotIn("official https://astral.sh/uv/install.ps1", self.calls())

    def test_preview_pwsh_alone_is_a_fail_that_offers_the_stable_install(self) -> None:
        # A preview build is another product: the stable one still has to be installed.
        self.fake_winget(0)
        self.fake_pwsh("7.7.0-preview.1")
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["S2"]["verdict"], "fail")
        self.assertIn("-Install pwsh", by_id["S2"]["action"])
        self.assertNotIn("-Update pwsh", by_id["S2"]["action"])

    def test_same_pwsh_version_on_two_paths_is_shown_once(self) -> None:
        other = self.root / "fakebin2"
        self.fake_pwsh("7.6.1")
        self.fake_pwsh("7.6.1", other)
        _, _, by_id = self.run_json(
            "-Lang", "en", env={"PATH": "%s;%s" % (self.bin, other)})
        self.assertEqual(by_id["S2"]["verdict"], "ok", by_id["S2"])
        self.assertNotIn("fakebin2", by_id["S2"]["detail"])
        self.assertNotIn("S2-paths", by_id)

    def test_lang_ko_has_no_english_sentence_after_a_failed_install(self) -> None:
        self.fake_winget(0x8A150107)
        _, out = self.run_setup("-Install", "uv", "-Lang", "ko")
        self.assertEqual(english_sentence_lines(out), [], out)


#: GATEKIT_SETUP_PWSH_PACKAGES values: what Get-AppxPackage would answer.
STABLE_PKG = "Microsoft.PowerShell=%s"
PREVIEW_PKG = "Microsoft.PowerShellPreview=7.7.5.0"


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupPwshProduct(SetupCase):
    """S2 follows the installed stable PRODUCT (package, then MSI folder, then the PATH
    version text), not the PATH order."""

    def s2(self, packages: str = "none", **env):
        environment = {"GATEKIT_SETUP_PWSH_PACKAGES": packages}
        environment.update(env)
        code, _, by_id = self.run_json("-Lang", "en", env=environment)
        return code, by_id["S2"], by_id

    def test_stable_package_is_ok_even_when_a_preview_comes_first_on_path(self) -> None:
        self.fake_pwsh("7.7.0-preview.5")
        _, item, by_id = self.s2(STABLE_PKG % "7.6.6.0" + ";" + PREVIEW_PKG)
        self.assertEqual(item["verdict"], "ok", item)
        self.assertEqual(item["level"], "required")
        self.assertIn("stable 7.6.6", item["detail"])
        self.assertIn("package Microsoft.PowerShell", item["detail"])
        self.assertIn("a preview build comes first on PATH", item["detail"])
        self.assertEqual(item["action"], "")
        self.assertIn("installed 7.6.6", by_id["P-pwsh"]["detail"])

    def test_stable_package_without_a_preview_has_no_preview_note(self) -> None:
        self.fake_pwsh("7.6.6")
        _, item, _ = self.s2(STABLE_PKG % "7.6.6.0")
        self.assertEqual(item["verdict"], "ok", item)
        self.assertNotIn("preview", item["detail"])

    def test_stable_package_below_the_minimum_fails_and_offers_the_update(self) -> None:
        self.fake_pwsh("7.5.1")
        code, item, _ = self.s2(STABLE_PKG % "7.5.1.0")
        self.assertEqual(item["verdict"], "fail", item)
        self.assertIn("-Update pwsh", item["action"])
        self.assertNotIn("-Install", item["action"])
        self.assertEqual(code, 2)

    def test_old_stable_on_path_only_fails_and_offers_the_update(self) -> None:
        self.fake_pwsh("7.5.0")
        _, item, _ = self.s2()
        self.assertEqual(item["verdict"], "fail", item)
        self.assertIn("-Update pwsh", item["action"])

    def test_preview_package_only_fails_and_offers_the_install(self) -> None:
        self.fake_winget(0)
        code, item, _ = self.s2(PREVIEW_PKG)
        self.assertEqual(item["verdict"], "fail", item)
        self.assertIn("preview", item["detail"])
        self.assertIn("-Install pwsh", item["action"])
        self.assertNotIn("-Update", item["action"])
        self.assertEqual(code, 2)

    def test_preview_on_path_only_fails_and_offers_the_install(self) -> None:
        self.fake_winget(0)
        self.fake_pwsh("7.7.0-preview.1")
        _, item, _ = self.s2()
        self.assertEqual(item["verdict"], "fail", item)
        self.assertIn("-Install pwsh", item["action"])
        self.assertNotIn("-Update pwsh", item["action"])

    def test_install_pwsh_is_not_skipped_when_only_a_preview_is_installed(self) -> None:
        self.fake_winget(0)
        self.fake_pwsh("7.7.0-preview.1")
        self.run_setup("-Install", "pwsh", "-Lang", "en")
        installs = [c for c in self.calls() if c.startswith("winget install")]
        self.assertEqual(len(installs), 1, self.calls())
        self.assertIn("--id Microsoft.PowerShell -e", installs[0])

    def test_install_pwsh_is_skipped_when_the_stable_package_is_there(self) -> None:
        self.fake_winget(0)
        self.fake_pwsh("7.7.0-preview.1")
        self.run_setup("-Install", "pwsh", "-Lang", "en",
                       env={"GATEKIT_SETUP_PWSH_PACKAGES": STABLE_PKG % "7.6.6.0"})
        self.assertEqual([c for c in self.calls() if c.startswith("winget install")], [])

    def test_stable_package_that_is_not_on_the_session_path_is_warn_and_exit_3(self) -> None:
        code, item, _ = self.s2(STABLE_PKG % "7.6.6.0")
        self.assertEqual(item["verdict"], "warn", item)
        self.assertIn("not visible", item["detail"])
        self.assertIn("close Claude Code completely (the desktop app, the VS Code window, "
                      "or the terminal it runs in) and open it again", item["action"])
        self.assertEqual(code, 3)

    def test_nothing_installed_offers_winget_and_pwsh_together_when_winget_is_missing(self) -> None:
        _, item, by_id = self.s2()
        self.assertEqual(item["verdict"], "fail", item)
        self.assertIn("-Install winget,pwsh", item["action"])
        self.assertEqual(by_id["S3"]["verdict"], "warn")
        self.assertEqual(by_id["S3"]["level"], "recommended")
        self.assertIn("-Install winget", by_id["S3"]["action"])

    def test_nothing_installed_offers_only_pwsh_when_winget_is_there(self) -> None:
        self.fake_winget(0)
        _, item, _ = self.s2()
        self.assertEqual(item["verdict"], "fail", item)
        self.assertIn("-Install pwsh", item["action"])
        self.assertNotIn("winget,pwsh", item["action"])

    def test_msi_folder_is_the_second_source(self) -> None:
        program_files = self.root / "Program Files"
        preview = program_files / "PowerShell" / "7-preview"
        preview.mkdir(parents=True)
        (preview / "pwsh.exe").write_bytes(b"")
        _, item, _ = self.s2(ProgramFiles=str(program_files))
        self.assertEqual(item["verdict"], "fail", item)  # a preview alone does not count
        self.assertIn("-Install", item["action"])
        stable = program_files / "PowerShell" / "7"
        stable.mkdir()
        (stable / "pwsh.exe").write_bytes(b"")  # found, but a fake file has no version
        _, item, _ = self.s2(ProgramFiles=str(program_files))
        self.assertEqual(item["verdict"], "unverified", item)
        self.assertIn("MSI", item["detail"])

    def test_package_wins_over_the_msi_folder_and_the_path(self) -> None:
        self.fake_pwsh("7.5.0")
        _, item, _ = self.s2(STABLE_PKG % "7.6.6.0")
        self.assertEqual(item["verdict"], "ok", item)
        self.assertIn("stable 7.6.6", item["detail"])

    def test_korean_lines_have_no_english_sentence(self) -> None:
        self.fake_pwsh("7.7.0-preview.5")
        for packages in (STABLE_PKG % "7.6.6.0", STABLE_PKG % "7.5.0.0", PREVIEW_PKG, "none"):
            _, out = self.run_setup("-Lang", "ko", env={"GATEKIT_SETUP_PWSH_PACKAGES": packages})
            self.assertEqual(english_sentence_lines(out), [], out)

    def test_the_lookup_names_come_from_packages_json(self) -> None:
        # The lookup lives in common.ps1 (shared with session-check.ps1); no script hard-codes a name.
        common = (SCRIPTS / "common.ps1").read_bytes().decode("utf-8-sig")
        self.assertIn("Get-AppxPackage -Name $slot[1]", common)
        self.assertIn("GATEKIT_SETUP_PWSH_PACKAGES", common)
        for name in ("common.ps1", "setup.ps1", "session-check.ps1"):
            text = (SCRIPTS / name).read_bytes().decode("utf-8-sig")
            self.assertNotIn("Microsoft.PowerShell", text, name)  # appx_name / appx_preview_name

    def test_the_product_rule_is_defined_once_in_common_ps1(self) -> None:
        common = (SCRIPTS / "common.ps1").read_bytes().decode("utf-8-sig")
        for func in ("ConvertTo-Version3", "Get-PwshPackages", "Get-PwshMsi", "Get-PwshProduct",
                     "Get-PwshFileKind"):
            self.assertEqual(common.count("function %s(" % func) + common.count("function %s {" % func), 1, func)
            for name in ("setup.ps1", "session-check.ps1"):
                text = (SCRIPTS / name).read_bytes().decode("utf-8-sig")
                self.assertNotIn("function " + func, text, "%s defines %s again" % (name, func))
        for name in ("setup.ps1", "session-check.ps1"):
            text = (SCRIPTS / name).read_bytes().decode("utf-8-sig")
            self.assertIn("Get-PwshProduct ", text, name)


#: A stand-in for the two winget install steps (GATEKIT_SETUP_WINGET_RUNNER). It logs
#: "wingetstep <step> <family>", prints TEXT and exits CODE. When the step is CREATE_ON it
#: creates a working fake winget on PATH (which logs its own calls).
FAKE_WINGET_RUNNER = r"""
import sys
step = sys.argv[1]
open(LOG, 'a').write('wingetstep ' + ' '.join(sys.argv[1:]) + chr(10))
if TEXT:
    print(TEXT)
if step == CREATE_ON:
    src = ("import sys" + chr(10)
           + "open(%r, 'a').write('winget ' + ' '.join(sys.argv[1:]) + chr(10))" % LOG + chr(10)
           + "if sys.argv[1] == '--version':" + chr(10) + "    print('v1.29.380')" + chr(10)
           + "sys.exit(0)" + chr(10))
    open(BIN + '/winget.fake.py', 'w').write(src)
    open(BIN + '/winget.cmd', 'w').write('@echo off' + chr(13) + chr(10)
                                         + '"%s" "%s" %%*' % (sys.executable, BIN + '/winget.fake.py')
                                         + chr(13) + chr(10))
sys.exit(CODE)
"""


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupInstallWinget(SetupCase):
    """-Install winget: register first (nothing downloaded), then the module repair, then the
    Microsoft Store link. Nothing real is installed: both steps go to a fake runner."""

    FAMILY = "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe"
    STORE = "https://apps.microsoft.com/detail/9nblggh4nns1"

    def runner(self, create_on: str = "", text: str = "", code: int = 0) -> dict:
        src = ("LOG = %r\nBIN = %r\nCREATE_ON = %r\nTEXT = %r\nCODE = %d\n"
               % (str(self.log), str(self.bin), create_on, text, code)) + FAKE_WINGET_RUNNER
        return {"GATEKIT_SETUP_WINGET_RUNNER": str(fakebin.make_fake(self.bin, "winget-runner", src))}

    def steps(self) -> list:
        return [c for c in self.calls() if c.startswith("wingetstep")]

    def records(self) -> list:
        path = self.root / ".gatekit" / "runs" / "setup-last.json"
        return json.loads(path.read_text(encoding="utf-8"))["failures"]

    def test_registering_is_tried_first_and_is_enough(self) -> None:
        _, _, by_id = self.run_json("-Install", "winget", "-Lang", "en", env=self.runner("register"))
        self.assertEqual(self.steps(), ["wingetstep register " + self.FAMILY])
        self.assertEqual(by_id["A-winget"]["verdict"], "ok", by_id["A-winget"])
        self.assertEqual(by_id["S3"]["verdict"], "ok", by_id["S3"])
        self.assertNotIn("S16-winget", by_id)

    def test_repair_runs_only_when_registering_was_not_enough(self) -> None:
        _, _, by_id = self.run_json("-Install", "winget", "-Lang", "en", env=self.runner("repair"))
        self.assertEqual(self.steps(), ["wingetstep register " + self.FAMILY,
                                        "wingetstep repair " + self.FAMILY])
        self.assertEqual(by_id["S3"]["verdict"], "ok", by_id["S3"])

    def test_still_missing_points_to_the_store_and_exits_2(self) -> None:
        code, _, by_id = self.run_json("-Install", "winget", "-Lang", "en", env=self.runner(""))
        item = by_id["S16-winget"]
        self.assertEqual(item["verdict"], "fail", item)
        self.assertEqual(item["level"], "recommended")
        self.assertIn("Microsoft Store", item["action"])
        self.assertIn(self.STORE, item["hints"])
        self.assertEqual(len(self.steps()), 2)
        self.assertEqual(code, 2)
        self.assertEqual([(r["item"], r["action"], r["class"]) for r in self.records()],
                         [("winget", "install", "store")])

    def test_policy_and_network_blocks_exit_4(self) -> None:
        cases = (("Add-AppxPackage : Deployment failed: blocked by group policy (0x80073D19)", "policy"),
                 ("Install-Module : Unable to download from URI: could not resolve host", "network"))
        for text, cls in cases:
            with self.subTest(cls=cls):
                code, _, by_id = self.run_json("-Install", "winget", "-Lang", "en",
                                               env=self.runner("", text=text, code=1))
                self.assertEqual(code, 4, by_id["S16-winget"])
                self.assertEqual(self.records()[0]["class"], cls)

    def test_the_real_commands_stay_in_user_scope(self) -> None:
        text = (SCRIPTS / "setup.ps1").read_bytes().decode("utf-8-sig")
        self.assertIn("Add-AppxPackage -RegisterByFamilyName -MainPackage ", text)
        self.assertIn("Install-PackageProvider -Name NuGet -Scope CurrentUser -Force", text)
        self.assertIn("Install-Module -Name Microsoft.WinGet.Client -Scope CurrentUser -Force -Repository PSGallery", text)
        code_lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
        self.assertTrue(any("Repair-WinGetPackageManager'" in line for line in code_lines))
        self.assertFalse(any("-AllUsers" in line or "Scope AllUsers" in line for line in code_lines))

    def test_winget_already_there_is_skipped(self) -> None:
        self.fake_winget(0)
        _, _, by_id = self.run_json("-Install", "winget", "-Lang", "en", env=self.runner("register"))
        self.assertEqual(self.steps(), [])
        self.assertIn("skipped", by_id["A-winget"]["detail"])

    def test_winget_is_installed_before_the_programs_that_need_it(self) -> None:
        self.run_setup("-Install", "pwsh,winget", "-Lang", "en", env=self.runner("register"))
        calls = self.calls()
        first_step = calls.index("wingetstep register " + self.FAMILY)
        installs = [i for i, c in enumerate(calls) if c.startswith("winget install --id Microsoft.PowerShell")]
        self.assertEqual(len(installs), 1, calls)
        self.assertLess(first_step, installs[0])

    def test_check_only_never_runs_a_winget_step(self) -> None:
        self.run_setup("-Lang", "en", env=self.runner("register"))
        self.assertEqual(self.steps(), [])

    def test_update_and_reinstall_of_winget_are_refused(self) -> None:
        for switch in ("-Update", "-Reinstall"):
            code, out = self.run_setup(switch, "winget", "-Lang", "en", env=self.runner("register"))
            self.assertEqual(code, 1, out)
            self.assertIn("refused", out)
        self.assertEqual(self.steps(), [])

    def test_retry_failed_retries_the_winget_install(self) -> None:
        self.run_setup("-Install", "winget", "-Lang", "en", env=self.runner(""))
        self.log.unlink()
        _, _, by_id = self.run_json("-RetryFailed", "-Lang", "en", env=self.runner("register"))
        self.assertEqual(self.steps(), ["wingetstep register " + self.FAMILY])
        self.assertIn("winget install", by_id["retry"]["detail"])
        self.assertEqual(self.records(), [])

    def test_a_failed_winget_install_is_named_as_the_cause_of_the_pwsh_failure(self) -> None:
        code, _, by_id = self.run_json("-Install", "winget,pwsh", "-Lang", "en", env=self.runner(""))
        item = by_id["S16-pwsh"]
        self.assertEqual(item["verdict"], "fail", item)
        self.assertIn("the winget install failed, so PowerShell 7 could not be installed", item["detail"])
        self.assertNotIn("-Install winget", item["action"])  # that is what just failed
        self.assertIn("winget install line above", item["action"])
        self.assertEqual(code, 2)
        classes = {r["item"]: r["class"] for r in self.records()}
        self.assertEqual(classes, {"winget": "store", "pwsh": "winget-failed"})

    def test_pwsh_without_a_winget_attempt_still_offers_the_winget_install(self) -> None:
        _, _, by_id = self.run_json("-Install", "pwsh", "-Lang", "en")
        self.assertIn("winget is missing", by_id["S16-pwsh"]["detail"])
        self.assertIn("-Install winget", by_id["S16-pwsh"]["action"])

    def test_a_failed_winget_install_then_pwsh_has_no_english_sentence_in_korean(self) -> None:
        _, out = self.run_setup("-Install", "winget,pwsh", "-Lang", "ko", env=self.runner(""))
        self.assertIn("winget 설치가 실패해서 PowerShell 7 을(를) 설치하지 못했습니다", out)
        self.assertNotIn("먼저 winget 설치를 허락", out)
        self.assertEqual(english_sentence_lines(out), [], out)

    def test_lang_ko_has_no_english_sentence(self) -> None:
        for create_on in ("", "repair"):  # the failing run first: the second one creates winget
            _, out = self.run_setup("-Install", "winget", "-Lang", "ko", env=self.runner(create_on))
            self.assertEqual(english_sentence_lines(out), [], out)
            if not create_on:
                self.assertIn(self.STORE, out)


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupSessionPath(SetupCase):
    def test_a_program_visible_only_in_the_registry_path_is_warn_and_exit_3(self) -> None:
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        fakebin.make_fake(elsewhere, "uv", "open(%r, 'a').write('uv called' + chr(10))\nprint('uv 0.10.7')\n"
                          % str(self.log))
        code, _, by_id = self.run_json("-Lang", "en", env={
            "GATEKIT_SETUP_KEEP_PATH": "", "GATEKIT_SETUP_REGISTRY_PATH": str(elsewhere)})
        self.assertEqual(by_id["S4"]["verdict"], "warn", by_id["S4"])
        self.assertEqual(code, 3)
        self.assertEqual(self.calls(), [])  # the check never ran the merged-path uv
        self.assertEqual(by_id["S5"]["verdict"], "unverified")

    def test_a_program_on_the_session_path_is_judged_normally(self) -> None:
        self.fake_uv()
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["S4"]["verdict"], "ok", by_id["S4"])


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupVenv(SetupCase):
    def damaged_venv(self, home: "pathlib.Path | None" = None) -> pathlib.Path:
        venv = self.kit / ".venv"
        (venv / "Scripts").mkdir(parents=True)
        (venv / "pyvenv.cfg").write_text("home = %s\nversion_info = 3.14.3\n" % (home or self.root),
                                         encoding="utf-8")
        (venv / "Scripts" / "python.exe").write_bytes(b"")  # 0 bytes: damaged
        return venv

    def test_no_python_default_mode_never_downloads_and_asks_for_permission(self) -> None:
        self.fake_uv("nopython")
        code, _, by_id = self.run_json("-Lang", "en")
        syncs = self.sync_calls()
        self.assertEqual(len(syncs), 1, self.calls())
        for flag in ("--frozen", "--no-dev", "--no-python-downloads"):
            self.assertIn(flag, syncs[0])
        self.assertEqual(by_id["S5"]["verdict"], "warn", by_id["S5"])
        self.assertIn("-Install venv", by_id["S5"]["action"])
        self.assertIn("tens of MB", by_id["S5"]["action"])
        self.assertEqual(code, 2)
        self.assertFalse((self.kit / ".venv").exists())

    def test_install_venv_downloads_and_builds_the_venv(self) -> None:
        self.fake_uv("nopython")
        code, _, by_id = self.run_json("-Install", "venv", "-Lang", "en")
        syncs = self.sync_calls()
        self.assertEqual(len(syncs), 1, self.calls())
        self.assertIn("--frozen", syncs[0])
        self.assertIn("--no-dev", syncs[0])  # hooks do not need the dev group
        self.assertNotIn("--no-python-downloads", syncs[0])
        self.assertEqual(by_id["S5"]["verdict"], "ok", by_id["S5"])
        self.assertTrue((self.kit / ".venv" / "Scripts" / "python.exe").is_file())

    def test_damaged_venv_default_mode_deletes_nothing_and_names_the_action(self) -> None:
        venv = self.damaged_venv()
        self.fake_uv("nopython")
        code, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["S5"]["verdict"], "fail")
        self.assertIn("0 bytes", by_id["S5"]["detail"])
        self.assertIn("-Install venv", by_id["S5"]["action"])
        self.assertIn(".claude/gatekit/.venv", by_id["S5"]["action"])
        self.assertEqual(code, 2)  # a permission fixes it: not exit 1
        self.assertTrue((venv / "pyvenv.cfg").exists())
        self.assertEqual(self.sync_calls(), [])

    def test_venv_whose_python_home_is_gone_is_only_recreated_with_install_venv(self) -> None:
        venv = self.damaged_venv(self.root / "no-such-python")
        (venv / "Scripts" / "python.exe").write_bytes(b"MZ")
        self.fake_uv("plain")
        code, out = self.run_setup("-Lang", "en")
        self.assertTrue((venv / "pyvenv.cfg").exists(), out)  # default mode: left alone
        self.assertEqual(self.sync_calls(), [])
        code, out = self.run_setup("-Install", "venv", "-Lang", "en")
        self.assertIn("deleting the damaged or outdated folder", out)
        self.assertFalse((venv / "pyvenv.cfg").exists(), out)  # removed; the plain fake builds nothing
        syncs = self.sync_calls()
        self.assertEqual(len(syncs), 1, self.calls())
        self.assertIn("--frozen", syncs[0])
        self.assertNotIn("--no-python-downloads", syncs[0])

    def test_damaged_venv_is_rebuilt_by_install_venv(self) -> None:
        self.damaged_venv()
        self.fake_uv("build")
        code, _, by_id = self.run_json("-Install", "venv", "-Lang", "en")
        self.assertEqual(by_id["S5"]["verdict"], "ok", by_id["S5"])
        self.assertGreater((self.kit / ".venv" / "Scripts" / "python.exe").stat().st_size, 0)

    def test_venv_python_below_3_14_warns_and_is_rebuilt_only_by_install_venv(self) -> None:
        self.fake_uv("build")
        self.run_setup("-Install", "venv", "-Lang", "en")
        marker = self.kit / ".venv" / "marker.txt"
        marker.write_text("x", encoding="utf-8")
        self.log.unlink()
        env = {"GATEKIT_SETUP_MIN_PYTHON": "3.99"}  # the fake venv now counts as too old
        code, _, by_id = self.run_json("-Lang", "en", env=env)
        self.assertEqual(by_id["S5"]["verdict"], "warn", by_id["S5"])
        self.assertIn("older than the required 3.99", by_id["S5"]["detail"])
        self.assertIn("-Install venv", by_id["S5"]["action"])
        self.assertEqual(code, 2)
        self.assertTrue(marker.exists())
        self.assertEqual(self.sync_calls(), [])
        code, out = self.run_setup("-Install", "venv", "-Lang", "en", env=env)
        self.assertIn("outdated folder", out)
        self.assertFalse(marker.exists(), out)  # deleted and rebuilt
        self.assertEqual(len(self.sync_calls()), 1)

    def test_minimum_python_comes_from_packages_json(self) -> None:
        self.fake_uv("build")
        self.run_setup("-Install", "venv", "-Lang", "en")
        pk = self.kit / "scripts" / "packages.json"
        data = json.loads(pk.read_text(encoding="utf-8"))
        data["python_min"] = "3.99"
        pk.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        code, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["S5"]["verdict"], "warn", by_id["S5"])
        self.assertIn("older than the required 3.99", by_id["S5"]["detail"])

    def test_default_minimum_python_is_3_14(self) -> None:
        text = (SCRIPTS / "setup.ps1").read_bytes().decode("utf-8-sig")
        self.assertIn("$pythonMinimum = [version]'3.14'", text)

    def test_healthy_venv_is_not_touched_by_install_venv(self) -> None:
        self.fake_uv("build")
        self.run_setup("-Install", "venv", "-Lang", "en")  # builds it
        marker = self.kit / ".venv" / "marker.txt"
        marker.write_text("x", encoding="utf-8")
        self.log.unlink()
        _, _, by_id = self.run_json("-Install", "venv", "-Lang", "en")
        self.assertTrue(marker.exists())
        self.assertEqual(self.sync_calls(), [])
        self.assertIn("skipped", by_id["S5"]["detail"])

    def test_default_check_of_a_healthy_venv_does_not_sync(self) -> None:
        self.fake_uv("build")
        self.run_setup("-Install", "venv", "-Lang", "en")
        self.log.unlink()
        self.run_setup("-Lang", "en")
        self.assertEqual(self.sync_calls(), [])  # a --no-dev sync would strip pyright and ruff

    def test_network_regex_uses_word_boundaries(self) -> None:
        self.fake_uv("fail", text="error: failed to build openssl-sys with rustls")
        code, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(code, 1, by_id["S5"])  # not misread as a network problem (exit 4)
        self.fake_uv("fail", text="error: SSL handshake failed")
        code, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(code, 4, by_id["S5"])

    def test_full_run_builds_a_venv_and_prints_korean_doctor_lines(self) -> None:
        self.copy_kit_sources()
        self.fake_uv("nopython")
        fakebin.make_fake(self.bin, "claude", "print('2.1.300 (Claude Code)')\n")
        code, out = self.run_setup("-Install", "venv", "-Lang", "ko")
        self.assertIn("[ok] .venv", out)
        self.assertIn("[ok] .gatekit/config.json", out)
        self.assertIn("gatekit 닥터", out)
        self.assertIn("설치 파일", out)
        self.assertEqual(english_sentence_lines(out), [], out)
        self.assertNotIn("fix:", out)

    def test_uv_sync_is_stopped_after_the_timeout_and_its_process_tree_is_killed(self) -> None:
        import time
        pidfile = self.root / "sync.pid"
        self.fake_uv("hang", pidfile=str(pidfile))
        started = time.monotonic()
        code, _, by_id = self.run_json("-Lang", "en", env={"GATEKIT_SETUP_SYNC_TIMEOUT": "4"})
        self.assertLess(time.monotonic() - started, 60)
        self.assertEqual(by_id["S5"]["verdict"], "fail", by_id["S5"])
        self.assertIn("4 seconds", by_id["S5"]["detail"])
        self.assertEqual(code, 4)
        pid = int(pidfile.read_text(encoding="ascii"))
        listing = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                                 capture_output=True, timeout=30).stdout.decode("utf-8", "replace")
        self.assertNotIn(str(pid), listing)  # the fake (a grandchild of the shim) is gone


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


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupRestoreAdvice(SetupCase):
    """A missing kit file: `git checkout` only when Git is on PATH and the project root is a
    Git work tree (`.git` folder or file); otherwise (a zip download) download the repository
    again and overwrite the file."""

    def fake_git(self, work_tree: str = "folder") -> None:
        """Git on PATH; *work_tree* is 'folder', 'file' (a linked work tree) or '' (a zip)."""
        fakebin.make_fake(self.bin, "git", "print('git version 2.54.0')\n")
        if work_tree == "folder":
            (self.root / ".git").mkdir(exist_ok=True)
        elif work_tree == "file":
            (self.root / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")

    def settings_action(self, lang: str = "en") -> str:
        (self.root / ".claude" / "settings.json").unlink(missing_ok=True)
        _, _, by_id = self.run_json("-Lang", lang)
        self.assertEqual(by_id["S12-settings"]["verdict"], "fail", by_id["S12-settings"])
        return by_id["S12-settings"]["action"]

    def test_without_git_the_advice_is_to_download_again(self) -> None:
        action = self.settings_action()
        self.assertIn("download the repository again and overwrite that file", action)
        self.assertIn(".claude/settings.json", action)
        self.assertNotIn("git checkout", action)
        self.assertIn("저장소를 다시 내려받아 그 파일을 덮어쓰세요", self.settings_action("ko"))

    def test_with_git_the_advice_is_git_checkout(self) -> None:
        self.fake_git()
        action = self.settings_action()
        self.assertIn("git checkout .claude/settings.json", action)
        self.assertNotIn("download the repository again", action)

    def test_a_git_file_instead_of_a_folder_is_a_work_tree_too(self) -> None:
        self.fake_git("file")
        self.assertIn("git checkout .claude/settings.json", self.settings_action())

    def test_git_without_a_repository_is_told_to_download_again(self) -> None:
        # A zip download on a PC that has Git: there is no .git, so git checkout would fail.
        self.fake_git("")
        action = self.settings_action()
        self.assertIn("not a Git repository", action)
        self.assertIn("download the repository again and overwrite that file", action)
        self.assertIn(".claude/settings.json", action)
        self.assertNotIn("git checkout", action)
        self.assertNotIn("Git is not installed", action)
        korean = self.settings_action("ko")
        self.assertIn("저장소를 다시 내려받아 그 파일을 덮어쓰세요", korean)
        self.assertNotIn("git checkout", korean)
        _, out = self.run_setup("-Lang", "ko")
        self.assertEqual(english_sentence_lines(out), [], out)
        (self.kit / "scripts" / "packages.json").write_text("{not json", encoding="utf-8")
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertNotIn("git checkout", by_id["args"]["action"])

    def test_broken_settings_and_packages_json_use_the_same_advice(self) -> None:
        (self.root / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertIn("download the repository again", by_id["S12-settings"]["action"])
        (self.kit / "scripts" / "packages.json").write_text("{not json", encoding="utf-8")
        code, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(code, 1)
        self.assertIn("download the repository again", by_id["args"]["action"])
        self.assertIn(".claude/gatekit/scripts/packages.json", by_id["args"]["action"])
        self.fake_git()
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertIn("git checkout .claude/gatekit/scripts/packages.json", by_id["args"]["action"])

    def test_unreadable_common_ps1_names_both_ways(self) -> None:
        # No shared function exists at that point, so Git cannot be looked up: both are printed.
        (self.kit / "scripts" / "common.ps1").unlink()
        for lang, without in (("en", "without Git: download the repository again"),
                              ("ko", "Git 이 없으면: 저장소를 다시 내려받아")):
            code, out = self.run_setup("-Lang", lang)
            self.assertEqual(code, 1, out)
            self.assertIn("git checkout .claude/gatekit/scripts/common.ps1", out)
            self.assertIn(without, out)
        code, out = self.run_setup("-Json", "-Lang", "ko")
        out.encode("ascii")
        data = json.loads(out)
        self.assertEqual((code, data["exit_code"]), (1, 1))
        self.assertEqual(len(data["items"][0]["hints"]), 2)

    def test_korean_lines_have_no_english_sentence(self) -> None:
        (self.root / ".claude" / "settings.json").unlink()
        _, out = self.run_setup("-Lang", "ko")
        self.assertEqual(english_sentence_lines(out), [], out)


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupPathLength(SetupCase):
    """S17: project folder + the longest relative path inside it against the 259 character limit."""

    def constants(self) -> tuple:
        text = (SCRIPTS / "setup.ps1").read_bytes().decode("utf-8-sig")
        found = []
        for name in ("longestTrackedPath", "longestVenvPath", "pathLimit"):
            match = re.search(r"^\$%s = (\d+)\s*$" % name, text, re.M)
            assert match is not None, name
            found.append(int(match.group(1)))
        return tuple(found)

    def use_root(self, root: pathlib.Path) -> None:
        """Move the scratch kit under *root*; later runs start setup.ps1 from there."""
        shutil.copytree(self.root / ".claude", root / ".claude")
        self.kit = root / ".claude" / "gatekit"

    def long_root(self, total: int) -> pathlib.Path:
        """A folder under the scratch root whose full path is exactly *total* characters."""
        base = self.root / "deep"
        pad = total - len(str(base)) - 1
        self.assertGreater(pad, 0, "the temp folder itself is too long for this test")
        root = base / ("p" * pad)
        root.mkdir(parents=True)
        self.assertEqual(len(str(root)), total)
        return root

    def s17(self, root: pathlib.Path, **env) -> dict:
        self.use_root(root)
        _, _, by_id = self.run_json("-Lang", "en", env=env)
        return by_id["S17"]

    def test_the_limit_is_259_characters(self) -> None:
        tracked, venv, limit = self.constants()
        self.assertEqual(limit, 259)  # MAX_PATH is 260 including the closing NUL
        self.assertGreaterEqual(min(tracked, venv), 50)

    def test_short_root_is_ok_and_shows_the_sum(self) -> None:
        tracked, venv, limit = self.constants()
        root = self.root / "short"
        item = self.s17(root)
        self.assertEqual(item["verdict"], "ok", item)
        total = len(str(root)) + 1 + max(tracked, venv)
        self.assertIn("%d characters to the longest file, limit %d" % (total, limit), item["detail"])

    def test_root_far_below_200_characters_already_warns(self) -> None:
        # The old rule only warned above 200 characters. The first root that does not fit:
        tracked, venv, limit = self.constants()
        first_bad = limit - max(tracked, venv)  # root + 1 + longest = limit + 1
        self.assertLess(first_bad, 200)
        item = self.s17(self.long_root(first_bad))
        self.assertEqual(item["verdict"], "warn", item)
        self.assertIn("is %d characters" % (limit + 1), item["detail"])
        self.assertIn("shorter folder", item["action"])

    def test_the_longest_root_that_fits_is_ok(self) -> None:
        tracked, venv, limit = self.constants()
        item = self.s17(self.long_root(limit - max(tracked, venv) - 1))
        self.assertEqual(item["verdict"], "ok", item)

    def test_long_paths_enabled_means_no_warning(self) -> None:
        tracked, venv, limit = self.constants()
        item = self.s17(self.long_root(limit - max(tracked, venv)), GATEKIT_SETUP_LONG_PATHS="1")
        self.assertEqual(item["verdict"], "ok", item)
        self.assertIn("LongPathsEnabled = 1", item["detail"])

    def test_the_script_only_reads_and_never_unblocks(self) -> None:
        text = (SCRIPTS / "setup.ps1").read_bytes().decode("utf-8-sig")
        self.assertIn("-Name 'LongPathsEnabled'", text)
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            for writer in ("Set-ItemProperty", "New-ItemProperty", "Set-ExecutionPolicy", "reg add"):
                self.assertNotIn(writer, line)
            if "Unblock-File" in line:  # only as text printed for the user, never as a command
                self.assertIn(r"'Get-ChildItem .claude\gatekit\scripts\*.ps1 | Unblock-File'", line)

    def test_no_tracked_file_is_longer_than_the_constant(self) -> None:
        git = shutil.which("git")
        if not git or not (PROJECT / ".git").exists():
            self.skipTest("needs git and a checkout")
        listed = subprocess.run([git, "-C", str(PROJECT), "ls-files"], capture_output=True, timeout=60)
        longest = max(len(line) for line in listed.stdout.decode("utf-8", "replace").splitlines())
        self.assertLessEqual(longest, self.constants()[0],
                             "a tracked path grew: measure again and raise $longestTrackedPath in setup.ps1")

    def test_korean_lines_have_no_english_sentence(self) -> None:
        tracked, venv, limit = self.constants()
        self.use_root(self.long_root(limit - max(tracked, venv)))
        out = ""
        for long_paths in ("0", "1"):
            _, out = self.run_setup("-Lang", "ko", env={"GATEKIT_SETUP_LONG_PATHS": long_paths})
            self.assertEqual(english_sentence_lines(out), [], out)
        self.assertIn("LongPathsEnabled = 1", out)


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupGroupPolicyExecutionPolicy(SetupCase):
    """S20: a group policy that pins the execution policy beats the hooks' -ExecutionPolicy Bypass."""

    def s20(self, value: str):
        code, _, by_id = self.run_json("-Lang", "en", env={"GATEKIT_SETUP_EXECUTION_POLICY": value})
        return code, by_id["S20"]

    def test_all_signed_or_restricted_is_a_policy_block_exit_4(self) -> None:
        for value, scope in (("MachinePolicy=AllSigned", "MachinePolicy"),
                             ("MachinePolicy=Restricted;UserPolicy=Undefined", "MachinePolicy"),
                             ("UserPolicy=AllSigned", "UserPolicy"),
                             ("MachinePolicy=Undefined;UserPolicy=Restricted", "UserPolicy")):
            with self.subTest(value=value):
                code, item = self.s20(value)
                self.assertEqual(item["verdict"], "fail", item)
                self.assertEqual(item["level"], "required")
                self.assertEqual(code, 4)  # beats the exit 2 of the missing uv
                self.assertIn("-ExecutionPolicy Bypass", item["detail"])
                self.assertIn("Do not work around the policy", item["action"])
                self.assertEqual(len(item["hints"]), 1)
                self.assertIn("Message for your IT contact", item["hints"][0])
                self.assertIn("(%s)" % scope, item["hints"][0])

    def test_machine_policy_wins_over_user_policy(self) -> None:
        code, item = self.s20("MachinePolicy=RemoteSigned;UserPolicy=AllSigned")
        self.assertEqual(item["verdict"], "ok", item)
        self.assertIn("RemoteSigned", item["detail"])
        self.assertEqual(code, 2)

    def test_no_group_policy_is_ok(self) -> None:
        for value in ("MachinePolicy=Undefined;UserPolicy=Undefined", "MachinePolicy=Unrestricted",
                      "UserPolicy=Bypass"):
            with self.subTest(value=value):
                code, item = self.s20(value)
                self.assertEqual(item["verdict"], "ok", item)
                self.assertEqual(code, 2)

    def test_without_the_hook_the_real_policy_of_this_pc_is_read(self) -> None:
        # An empty value counts as not set: Get-ExecutionPolicy -List answers (read-only).
        _, item = self.s20("")
        self.assertIn(item["verdict"], ("ok", "fail"), item)
        self.assertIn("MachinePolicy=", item["detail"])
        self.assertIn("Get-ExecutionPolicy -List",
                      (SCRIPTS / "setup.ps1").read_bytes().decode("utf-8-sig"))

    def test_korean_lines_have_no_english_sentence(self) -> None:
        for value in ("MachinePolicy=AllSigned", "UserPolicy=RemoteSigned", "UserPolicy=Undefined"):
            _, out = self.run_setup("-Lang", "ko", env={"GATEKIT_SETUP_EXECUTION_POLICY": value})
            self.assertEqual(english_sentence_lines(out), [], out)


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupInternetMark(SetupCase):
    """S8 looks at every scripts/*.ps1, names the marked files and prints the Unblock-File line."""

    UNBLOCK = r"Get-ChildItem .claude\gatekit\scripts\*.ps1 | Unblock-File"

    def setUp(self) -> None:
        super().setUp()
        for name in ("session-check.ps1", "verify.ps1"):
            shutil.copy(SCRIPTS / name, self.kit / "scripts" / name)

    def mark(self, name: str) -> str:
        stream = str(self.kit / "scripts" / name) + ":Zone.Identifier"
        try:
            with open(stream, "w", encoding="ascii") as handle:
                handle.write("[ZoneTransfer]\nZoneId=3\n")
        except OSError:
            self.skipTest("this file system has no alternate data streams")
        return stream

    def test_no_mark_is_ok_and_counts_all_four_scripts(self) -> None:
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["S8"]["verdict"], "ok", by_id["S8"])
        self.assertIn("4 .ps1 files", by_id["S8"]["detail"])
        self.assertEqual(by_id["S8"]["hints"], [])

    def test_a_mark_on_another_script_is_named_with_the_unblock_command(self) -> None:
        for name in ("session-check.ps1", "common.ps1", "verify.ps1"):
            self.mark(name)
        _, _, by_id = self.run_json("-Lang", "en")
        item = by_id["S8"]
        self.assertEqual(item["verdict"], "info", item)  # Bypass still runs them
        self.assertIn("common.ps1, session-check.ps1, verify.ps1", item["detail"])
        self.assertNotIn("setup.ps1", item["detail"])
        self.assertEqual(len(item["hints"]), 2)
        self.assertEqual(item["hints"][1], self.UNBLOCK)

    def test_the_mark_is_never_removed_by_the_script(self) -> None:
        stream = self.mark("setup.ps1")
        self.run_setup("-Lang", "en")
        self.run_setup("-Install", "uv,venv", "-Lang", "en", env={
            "GATEKIT_SETUP_OFFICIAL_RUNNER": self.fake_official_runner(1)})
        with open(stream, encoding="ascii") as handle:
            self.assertIn("ZoneId=3", handle.read())

    def test_remote_signed_group_policy_makes_the_mark_a_warning(self) -> None:
        self.mark("session-check.ps1")
        _, _, by_id = self.run_json("-Lang", "en", env={
            "GATEKIT_SETUP_EXECUTION_POLICY": "MachinePolicy=RemoteSigned"})
        self.assertEqual(by_id["S8"]["verdict"], "warn", by_id["S8"])
        self.assertIn("do not run", by_id["S8"]["detail"])
        self.assertIn(self.UNBLOCK, by_id["S8"]["hints"])

    def test_korean_lines_have_no_english_sentence(self) -> None:
        self.mark("common.ps1")
        for policy in ("MachinePolicy=Undefined", "MachinePolicy=RemoteSigned"):
            _, out = self.run_setup("-Lang", "ko", env={"GATEKIT_SETUP_EXECUTION_POLICY": policy})
            self.assertEqual(english_sentence_lines(out), [], out)
            self.assertIn(self.UNBLOCK, out)


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupExecDenied(SetupCase):
    """A program that exists but that Windows refuses to start because of a policy (error 1260 /
    4551) is a policy block (exit 4), not "reinstall it". GATEKIT_SETUP_EXEC_DENIED stands in for
    the refusal; a start failure of another kind keeps the older handling."""

    def test_denied_uv_is_exit_4_without_a_reinstall_offer(self) -> None:
        self.fake_uv()
        code, _, by_id = self.run_json("-Lang", "en", env={"GATEKIT_SETUP_EXEC_DENIED": "uv"})
        item = by_id["S4"]
        self.assertEqual(item["verdict"], "fail", item)
        self.assertIn("policy blocks uv from running (Windows error 1260)", item["detail"])
        self.assertNotIn("-Install", item["action"])
        self.assertNotIn("-Update", item["action"])
        self.assertIn("a reinstall does not fix this", item["action"])
        self.assertIn("Message for your IT contact", item["hints"][0])
        self.assertEqual(code, 4)
        self.assertEqual(by_id["S5"]["verdict"], "unverified")
        self.assertEqual(self.calls(), [])  # uv was never started

    def test_a_uv_that_is_not_a_program_keeps_the_reinstall_offer(self) -> None:
        # A real start failure of another kind (Windows error 193): it cannot be told apart from
        # a damaged file, so the older advice stays.
        (self.bin / "uv.exe").write_bytes(b"not a program")
        code, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["S4"]["verdict"], "fail", by_id["S4"])
        self.assertIn("-Install uv", by_id["S4"]["action"])
        self.assertEqual(code, 2)

    def test_start_errors_are_read_from_the_win32_exception(self) -> None:
        text = (SCRIPTS / "setup.ps1").read_bytes().decode("utf-8-sig")
        self.assertIn("[System.ComponentModel.Win32Exception]", text)
        self.assertIn("$r.StartError -eq 1260 -or $r.StartError -eq 4551", text)

    def test_denied_venv_python_is_exit_4_and_the_venv_is_never_deleted(self) -> None:
        self.fake_uv("build")
        self.run_setup("-Install", "venv", "-Lang", "en")  # builds a working .venv
        marker = self.kit / ".venv" / "marker.txt"
        marker.write_text("x", encoding="utf-8")
        self.log.unlink()
        for extra in ((), ("-Install", "venv")):
            with self.subTest(extra=extra):
                code, _, by_id = self.run_json(*extra, "-Lang", "en",
                                               env={"GATEKIT_SETUP_EXEC_DENIED": "python"})
                item = by_id["S5"]
                self.assertEqual(item["verdict"], "fail", item)
                self.assertIn("Windows error 1260", item["detail"])
                self.assertIn("hooks are off", item["detail"])
                self.assertNotIn("-Install venv", item["action"])
                self.assertIn("Message for your IT contact", item["hints"][0])
                self.assertEqual(code, 4)
                self.assertTrue(marker.exists())  # not deleted, not rebuilt
                self.assertEqual(self.sync_calls(), [])
                self.assertNotIn("S5-delete", by_id)

    def test_korean_lines_have_no_english_sentence(self) -> None:
        self.fake_uv("build")
        self.run_setup("-Install", "venv", "-Lang", "en")
        for denied in ("uv", "python"):
            _, out = self.run_setup("-Lang", "ko", env={"GATEKIT_SETUP_EXEC_DENIED": denied})
            self.assertEqual(english_sentence_lines(out), [], out)
            self.assertIn("IT 담당자에게 보낼 문의문", out)


if __name__ == "__main__":
    unittest.main()
