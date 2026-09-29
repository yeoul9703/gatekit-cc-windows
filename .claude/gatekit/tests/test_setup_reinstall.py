"""setup.ps1 -Reinstall <uv|pwsh|claude>: allowed list, the right command per tool and
install method, agreement flags only for the listed name, and the version re-check.

Nothing is installed: winget and the official installer script are fake executables
that record their arguments (GATEKIT_SETUP_OFFICIAL_RUNNER)."""
from __future__ import annotations

import json
import unittest

from tests import fakebin
from tests.test_scripts import POWERSHELL, SetupCase

UV_URL = "https://astral.sh/uv/install.ps1"
CLAUDE_URL = "https://claude.ai/install.ps1"


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestReinstall(SetupCase):
    def winget_calls(self, verb: str = "install") -> list:
        return [c for c in self.calls() if c.startswith("winget " + verb)]

    def official_calls(self) -> list:
        return [c for c in self.calls() if c.startswith("official ")]

    def receipt(self, text: str):
        path = self.local / "uv" / "uv-receipt.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def winget_uv(self) -> None:
        """A uv that lives under a WinGet folder, so the install method reads as winget."""
        folder = self.root / "AppData" / "WinGet" / "Links"
        folder.mkdir(parents=True)
        src = ("import sys\n"
               "open(%r, 'a').write('uv ' + ' '.join(sys.argv[1:]) + chr(10))\n"
               "print('uv 0.10.7 (fake)')\n" % str(self.log))
        fakebin.make_fake(folder, "uv", src)
        self.winget_dir = folder

    def test_disallowed_names_are_refused_with_exit_1(self) -> None:
        self.fake_winget(0)
        runner = self.fake_official_runner(0)
        for name in ("git", "venv", "foo", "winget"):
            with self.subTest(name=name):
                code, out = self.run_setup("-Reinstall", name, "-Lang", "en",
                                           env={"GATEKIT_SETUP_OFFICIAL_RUNNER": runner})
                self.assertEqual(code, 1, out)
                self.assertIn("refused", out)
        self.assertEqual(self.winget_calls(), [])
        self.assertEqual(self.official_calls(), [])

    def test_git_refusal_prints_the_manual_command(self) -> None:
        code, out = self.run_setup("-Reinstall", "git", "-Lang", "en")
        self.assertEqual(code, 1, out)
        self.assertIn("winget install --id Git.Git", out)
        self.assertIn("administrator", out)

    def test_one_bad_name_stops_the_good_ones_too(self) -> None:
        self.fake_winget(0)
        self.fake_pwsh("7.6.0")
        code, out = self.run_setup("-Reinstall", "pwsh,git", "-Lang", "en")
        self.assertEqual(code, 1, out)
        self.assertEqual(self.winget_calls(), [])

    def test_uv_with_a_broken_receipt_is_repaired_by_the_official_script(self) -> None:
        self.fake_uv()
        self.fake_winget(0)
        receipt = self.receipt("{ not json")
        runner_src = ("import sys\n"
                      "open(%r, 'a').write('official ' + ' '.join(sys.argv[1:]) + chr(10))\n"
                      "open(%r, 'w').write('{}')\n" % (str(self.log), str(receipt)))
        runner = str(fakebin.make_fake(self.bin, "official-runner", runner_src))
        code, data, by_id = self.run_json("-Reinstall", "uv", "-Lang", "en",
                                          env={"GATEKIT_SETUP_OFFICIAL_RUNNER": runner})
        self.assertEqual(self.official_calls(), ["official " + UV_URL])
        self.assertEqual(self.winget_calls(), [])
        details = " | ".join(i["detail"] for i in data["items"] if i["id"] == "A-uv")
        self.assertIn("repair the broken uv-receipt.json", details)
        self.assertEqual(by_id["A-uv-receipt"]["verdict"], "ok", by_id["A-uv-receipt"])
        self.assertEqual(by_id["A-uv-version"]["verdict"], "ok")
        self.assertIn("0.10.7", by_id["A-uv-version"]["detail"])
        self.assertIn("uv reinstall", by_id["S11"]["detail"])  # listed as done

    def test_uv_reinstall_whose_receipt_stays_broken_says_so(self) -> None:
        self.fake_uv()
        self.receipt("{ not json")
        runner = self.fake_official_runner(0)
        _, _, by_id = self.run_json("-Reinstall", "uv", "-Lang", "en",
                                    env={"GATEKIT_SETUP_OFFICIAL_RUNNER": runner})
        self.assertEqual(by_id["A-uv-receipt"]["verdict"], "warn")

    def test_winget_installed_uv_is_reinstalled_with_force_through_winget(self) -> None:
        self.winget_uv()
        self.fake_winget(0)
        runner = self.fake_official_runner(0)
        code, out = self.run_setup("-Reinstall", "uv", "-Lang", "en", env={
            "PATH": "%s;%s" % (self.bin, self.winget_dir), "GATEKIT_SETUP_OFFICIAL_RUNNER": runner})
        calls = self.winget_calls()
        self.assertEqual(len(calls), 1, self.calls())
        for part in ("--id astral-sh.uv", "-e", "--force", "--source winget", "--disable-interactivity",
                     "--accept-source-agreements", "--accept-package-agreements"):
            self.assertIn(part, calls[0])
        self.assertEqual(self.official_calls(), [])

    def test_scoop_installed_uv_is_not_reinstalled_automatically(self) -> None:
        folder = self.root / "scoop" / "shims"
        folder.mkdir(parents=True)
        fakebin.make_fake(folder, "uv", "print('uv 0.10.7 (fake)')\n")
        self.fake_winget(0)
        runner = self.fake_official_runner(0)
        code, _, by_id = self.run_json("-Reinstall", "uv", "-Lang", "en", env={
            "PATH": "%s;%s" % (self.bin, folder), "GATEKIT_SETUP_OFFICIAL_RUNNER": runner})
        self.assertEqual(by_id["S16-uv"]["verdict"], "warn")
        self.assertIn("scoop update uv", by_id["S16-uv"]["action"])
        self.assertEqual(self.winget_calls(), [])
        self.assertEqual(self.official_calls(), [])

    def test_pwsh_is_reinstalled_with_winget_msix_force_and_reads_the_version_again(self) -> None:
        self.fake_winget(0)
        self.fake_pwsh("7.6.1")
        code, _, by_id = self.run_json("-Reinstall", "pwsh", "-Lang", "en")
        calls = self.winget_calls()
        self.assertEqual(len(calls), 1, self.calls())
        for part in ("--id Microsoft.PowerShell", "-e", "--installer-type msix", "--force",
                     "--accept-source-agreements", "--accept-package-agreements",
                     "--disable-interactivity"):
            self.assertIn(part, calls[0])
        self.assertEqual(self.winget_calls("upgrade"), [])
        self.assertIn("7.6.1", by_id["A-pwsh-version"]["detail"])
        for call in self.calls():
            if call not in calls:
                self.assertNotIn("--accept", call)  # agreements only for the listed name

    def test_claude_is_reinstalled_with_the_official_script_only(self) -> None:
        fakebin.make_fake(self.bin, "claude", "print('2.1.300 (Claude Code)')\n")
        self.fake_winget(0)
        runner = self.fake_official_runner(0)
        code, _, by_id = self.run_json("-Reinstall", "claude", "-Lang", "en",
                                       env={"GATEKIT_SETUP_OFFICIAL_RUNNER": runner})
        self.assertEqual(self.official_calls(), ["official " + CLAUDE_URL])
        self.assertEqual(self.winget_calls(), [])
        self.assertIn("2.1.300", by_id["A-claude-version"]["detail"])

    def test_missing_program_falls_back_to_a_plain_install(self) -> None:
        self.fake_winget(0)
        code, out = self.run_setup("-Reinstall", "pwsh", "-Lang", "en")
        calls = self.winget_calls()
        self.assertEqual(len(calls), 1, self.calls())
        self.assertNotIn("--force", calls[0])
        self.assertIn("not installed", out)

    def test_winget_failure_keeps_the_normal_exit_codes(self) -> None:
        self.fake_pwsh("7.6.0")
        for winget_code, exit_code in ((0x8A15003A, 4), (0x8A150999, 1)):
            with self.subTest(code=hex(winget_code)):
                self.fake_winget(winget_code)
                code, out = self.run_setup("-Reinstall", "pwsh", "-Lang", "en")
                self.assertEqual(code, exit_code, out)

    def test_failed_official_script_is_reported(self) -> None:
        self.fake_uv()
        self.receipt("{ not json")
        runner = self.fake_official_runner(1)
        code, out = self.run_setup("-Reinstall", "uv", "-Lang", "en",
                                   env={"GATEKIT_SETUP_OFFICIAL_RUNNER": runner})
        self.assertNotEqual(code, 0, out)
        self.assertIn("[fail]", out)

    def test_json_output_stays_ascii_for_reinstall(self) -> None:
        self.fake_winget(0)
        self.fake_pwsh("7.6.1")
        code, out = self.run_setup("-Json", "-Reinstall", "pwsh", "-Lang", "ko")
        out.encode("ascii")
        self.assertIn("A-pwsh", {i["id"] for i in json.loads(out)["items"]})


if __name__ == "__main__":
    unittest.main()
