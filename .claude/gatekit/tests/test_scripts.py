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




class TestSetupCommandText(unittest.TestCase):
    """S27: the command text covers warn candidates, -Update, -Install venv and -Lang."""

    def setUp(self) -> None:
        self.text = (PROJECT / ".claude" / "commands" / "gatekit" / "setup.md").read_text(encoding="utf-8")

    def test_candidates_include_warn_items_and_update_flow(self) -> None:
        self.assertIn("`fail` **or `warn`**", self.text)
        self.assertIn("-Update uv", self.text)
        self.assertIn("-Update pwsh", self.text)
        self.assertIn("-Update claude", self.text)

    def test_venv_question_mentions_the_download_size(self) -> None:
        self.assertIn("-Install venv", self.text)
        self.assertIn("tens of MB", self.text)
        self.assertIn("deleted and rebuilt", self.text)

    def test_every_setup_call_passes_lang(self) -> None:
        calls = [line for line in self.text.splitlines() if "scripts/setup.ps1" in line and "-File" in line]
        self.assertGreaterEqual(len(calls), 2)
        for line in calls:
            self.assertIn("-Lang", line)
        self.assertIn("Always pass `-Lang <output_lang>`", self.text)


def base_env(bin_dir: pathlib.Path, local_app: pathlib.Path) -> dict:
    """A scratch environment: only the fakes on PATH, no inherited policy
    override (PSExecutionPolicyPreference is deliberately absent)."""
    return {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
            "PATH": str(bin_dir), "PATHEXT": ".EXE;.CMD",
            "LOCALAPPDATA": str(local_app),
            "GATEKIT_SETUP_KEEP_PATH": "1"}


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
        for name in ("gatekit", "bin", "policy"):
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
            self.assertNotIn("Git.Git", call)

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

    def test_preview_pwsh_points_to_update_not_install(self) -> None:
        self.fake_pwsh("7.7.0-preview.1")
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["S2"]["verdict"], "warn")
        self.assertIn("-Update pwsh", by_id["S2"]["action"])
        self.assertNotIn("-Install pwsh", by_id["S2"]["action"])

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


if __name__ == "__main__":
    unittest.main()
