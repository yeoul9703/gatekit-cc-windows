"""setup.ps1 package management: the package table (installed version, update available,
install method), the failure record .gatekit/runs/setup-last.json, -RetryFailed and -Status.

winget is a fake executable: it logs its arguments, answers `list` from a table in the test,
and (when asked) really creates the fake program on `install`, so success paths run end to end.
"""
from __future__ import annotations

import json
import time
import unittest

from tests import fakebin
from tests.test_scripts import POWERSHELL, SetupCase, english_sentence_lines

HEADER = "Name  Id  Version  Available  Source\n----\n"


def row(name: str, pid: str, version: str, available: str = "", source: str = "winget") -> str:
    parts = [name.ljust(18), pid.ljust(22), version.ljust(10), available.ljust(10) if available else "", source]
    return HEADER + "".join(parts).rstrip() + "\n"


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class PackagesCase(SetupCase):
    def winget(self, listing=None, search=0, install=0, creates=None, list_sleep=0.0) -> None:
        """listing: {winget id: text of `winget list`}; an id that is missing answers 'not found'.
        creates: {'install': ['pwsh', ...]} programs the fake really creates on install/upgrade."""
        src = (
            "import sys, time\n"
            "LOG = %r\nLISTING = %r\nSEARCH = %d\nINSTALL = %d\nCREATES = %r\nBIN = %r\nSLEEP = %r\n"
            "a = sys.argv[1:]\n"
            "open(LOG, 'a').write('winget ' + ' '.join(a) + chr(10))\n"
            "if a[0] == '--version':\n"
            "    print('v1.29.380'); sys.exit(0)\n"
            "if a[0] == 'search':\n"
            "    sys.exit(SEARCH)\n"
            "if a[0] == 'list':\n"
            "    time.sleep(SLEEP)\n"
            "    text = LISTING.get(a[a.index('--id') + 1])\n"
            "    if text is None:\n"
            "        print('No installed package found matching input criteria.'); sys.exit(2316632084)\n"
            "    print(text); sys.exit(0)\n"
            "if INSTALL == 0:\n"
            "    for name in CREATES:\n"
            "        open(BIN + '/' + name + '.cmd', 'w').write('@echo off' + chr(13) + chr(10) + 'echo 7.6.1' + chr(13) + chr(10))\n"
            "sys.exit(INSTALL)\n"
            % (str(self.log), listing or {}, search, install, list(creates or []), str(self.bin), list_sleep))
        fakebin.make_fake(self.bin, "winget", src)

    @property
    def record_file(self):
        return self.root / ".gatekit" / "runs" / "setup-last.json"

    def records(self) -> list:
        return json.loads(self.record_file.read_text(encoding="utf-8"))["failures"]

    def winget_calls(self, verb: str) -> list:
        return [c for c in self.calls() if c.startswith("winget " + verb)]


class TestPackageTable(PackagesCase):
    def test_update_available_is_shown_with_the_version_and_the_switch(self) -> None:
        self.fake_uv()
        self.winget({"astral-sh.uv": row("uv", "astral-sh.uv", "0.10.7", "0.11.0")})
        _, _, by_id = self.run_json("-Lang", "en")
        item = by_id["P-uv"]
        self.assertEqual(item["verdict"], "warn", item)
        self.assertIn("update available: 0.11.0", item["detail"])
        self.assertIn("installed 0.10.7", item["detail"])
        self.assertIn("method: winget", item["detail"])
        self.assertIn("-Update uv", item["action"])
        self.assertEqual(item["level"], "required")

    def test_up_to_date_is_ok_and_the_lookup_is_read_only(self) -> None:
        self.fake_uv()
        self.winget({"astral-sh.uv": row("uv", "astral-sh.uv", "0.10.7")})
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["P-uv"]["verdict"], "ok", by_id["P-uv"])
        lookups = self.winget_calls("list")
        self.assertEqual(len(lookups), 1, self.calls())
        for part in ("--id astral-sh.uv", "-e", "--disable-interactivity"):
            self.assertIn(part, lookups[0])
        for call in self.calls():
            self.assertNotIn("--accept", call)
            self.assertNotIn(" install ", " " + call + " ")

    def test_winget_row_for_a_different_install_is_flagged(self) -> None:
        self.fake_pwsh("7.7.0-preview.5")  # the first pwsh on PATH is a preview build
        self.winget({"Microsoft.PowerShell": row("PowerShell", "Microsoft.PowerShell", "7.6.1")})
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertIn("installed 7.7.0-preview.5", by_id["P-pwsh"]["detail"])
        self.assertIn("winget lists a different install, 7.6.1", by_id["P-pwsh"]["detail"])

    def test_not_managed_by_winget_is_unverified(self) -> None:
        self.fake_uv()
        self.winget({})
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["P-uv"]["verdict"], "unverified", by_id["P-uv"])
        self.assertIn("not a winget-managed install", by_id["P-uv"]["detail"])

    def test_unaccepted_agreements_mean_no_lookup_at_all(self) -> None:
        self.fake_uv()
        self.winget({"astral-sh.uv": row("uv", "astral-sh.uv", "0.10.7", "0.11.0")}, search=0x8A150046)
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["P-uv"]["verdict"], "unverified")
        self.assertIn("agreements are not confirmed", by_id["P-uv"]["detail"])
        self.assertEqual(self.winget_calls("list"), [])

    def test_missing_winget_means_no_lookup(self) -> None:
        self.fake_uv()
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["P-uv"]["verdict"], "unverified")
        self.assertIn("winget is missing", by_id["P-uv"]["detail"])

    def test_lookup_has_a_timeout_and_kills_the_process(self) -> None:
        self.fake_uv()
        self.winget({"astral-sh.uv": row("uv", "astral-sh.uv", "0.10.7")}, list_sleep=60)
        started = time.time()
        _, _, by_id = self.run_json("-Lang", "en", env={"GATEKIT_SETUP_LIST_TIMEOUT": "2"})
        self.assertLess(time.time() - started, 50)
        self.assertEqual(by_id["P-uv"]["verdict"], "unverified")
        self.assertIn("in time", by_id["P-uv"]["detail"])

    def test_missing_program_row_and_versions(self) -> None:
        self.fake_uv()
        self.fake_pwsh("7.6.1")
        fakebin.make_fake(self.bin, "claude", "print('2.1.300 (Claude Code)')\n")
        fakebin.make_fake(self.bin, "git", "print('git version 2.54.0.windows.1')\n")
        self.winget({})
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertIn("installed 7.6.1", by_id["P-pwsh"]["detail"])
        self.assertIn("installed 2.1.300", by_id["P-claude"]["detail"])
        self.assertIn("installed 2.54.0", by_id["P-git"]["detail"])
        self.assertEqual(by_id["P-pwsh"]["level"], "recommended")
        self.assertEqual(by_id["P-git"]["level"], "info")

    def test_not_installed_row(self) -> None:
        self.winget({})
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertIn("not installed", by_id["P-pwsh"]["detail"])
        self.assertIn("Microsoft.PowerShell", by_id["P-pwsh"]["detail"])

    def test_install_method_from_path_and_from_winget(self) -> None:
        folder = self.root / "AppData" / "WinGet" / "Links"
        folder.mkdir(parents=True)
        fakebin.make_fake(folder, "uv", "print('uv 0.10.7 (fake)')\n")
        self.winget({})
        _, _, by_id = self.run_json("-Lang", "en", env={"PATH": "%s;%s" % (self.bin, folder)})
        self.assertIn("method: winget", by_id["P-uv"]["detail"])
        (self.local / "uv").mkdir()
        (self.local / "uv" / "uv-receipt.json").write_text("{}", encoding="utf-8")
        self.fake_uv()
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertIn("method: official script", by_id["P-uv"]["detail"])

    def test_korean_lines_carry_no_english_sentence(self) -> None:
        self.fake_uv()
        self.fake_pwsh("7.6.1")
        self.winget({"astral-sh.uv": row("uv", "astral-sh.uv", "0.10.7", "0.11.0")})
        code, out = self.run_setup("-Lang", "ko")
        lines = [line for line in out.splitlines() if "패키지" in line or "지난 실패 기록" in line]
        self.assertGreaterEqual(len(lines), 4, out)
        self.assertEqual(english_sentence_lines("\n".join(lines)), [])
        self.assertIn("업데이트 가능: 0.11.0", out)

    def test_plain_check_never_writes_a_record(self) -> None:
        self.fake_uv()
        self.winget({})
        self.run_setup("-Lang", "en")
        self.assertFalse((self.root / ".gatekit" / "runs").exists())


class TestFailureRecord(PackagesCase):
    def test_failed_install_is_recorded_with_all_fields(self) -> None:
        self.winget(install=0x8A15003A)
        code, _, by_id = self.run_json("-Install", "pwsh", "-Lang", "en")
        self.assertEqual(code, 4)
        recs = self.records()
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertEqual((rec["item"], rec["action"], rec["class"]), ("pwsh", "install", "policy"))
        self.assertEqual(rec["exit_hex"], "0x8A15003A")
        self.assertEqual(rec["exit_code"], 0x8A15003A - 2 ** 32)
        self.assertRegex(rec["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        self.assertIn("policy", rec["message"])
        self.assertEqual(by_id["P-failures"]["verdict"], "warn")
        self.assertIn("-RetryFailed", by_id["P-failures"]["action"])

    def test_record_is_ascii_json_even_for_korean_messages(self) -> None:
        self.winget(install=0x8A15003A)
        self.run_setup("-Install", "pwsh", "-Lang", "ko")
        raw = self.record_file.read_bytes()
        raw.decode("ascii")
        self.assertIn("정책", self.records()[0]["message"])
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))

    def test_update_and_reinstall_failures_keep_their_action(self) -> None:
        self.fake_pwsh("7.6.0")
        self.winget(install=0x8A150107)
        self.run_setup("-Update", "pwsh", "-Lang", "en")
        self.run_setup("-Reinstall", "pwsh", "-Lang", "en")
        actions = sorted((r["item"], r["action"], r["class"]) for r in self.records())
        self.assertEqual(actions, [("pwsh", "reinstall", "network"), ("pwsh", "update", "network")])

    def test_a_new_failure_replaces_the_older_one_of_the_same_item_and_action(self) -> None:
        self.winget(install=0x8A15003A)
        self.run_setup("-Install", "pwsh", "-Lang", "en")
        self.winget(install=0x8A150107)
        self.run_setup("-Install", "pwsh", "-Lang", "en")
        recs = self.records()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["class"], "network")

    def test_success_removes_that_item_only(self) -> None:
        self.winget(install=0x8A150107)
        self.run_setup("-Install", "pwsh,claude", "-Lang", "en",
                       env={"GATEKIT_SETUP_OFFICIAL_RUNNER": self.fake_official_runner(1)})
        self.assertEqual(sorted(r["item"] for r in self.records()), ["claude", "pwsh"])
        self.winget(creates=["pwsh"])
        code, _, by_id = self.run_json("-Install", "pwsh", "-Lang", "en")
        self.assertEqual(by_id["A-pwsh"]["verdict"], "ok", by_id["A-pwsh"])
        self.assertEqual([r["item"] for r in self.records()], ["claude"])

    def test_already_installed_counts_as_success(self) -> None:
        self.winget(install=0x8A150107)
        self.run_setup("-Install", "pwsh", "-Lang", "en")
        self.assertEqual(len(self.records()), 1)
        self.fake_pwsh("7.6.1")
        self.run_setup("-Install", "pwsh", "-Lang", "en")
        self.assertEqual(self.records(), [])

    def test_missing_winget_is_recorded(self) -> None:
        self.run_setup("-Install", "pwsh", "-Lang", "en")
        self.assertEqual(self.records()[0]["class"], "winget-missing")

    def test_failed_install_of_the_venv_is_recorded_and_cleared(self) -> None:
        self.fake_uv("fail", text="error: something broke")
        code, _, _ = self.run_json("-Install", "venv", "-Lang", "en")
        self.assertEqual(code, 1)
        self.assertEqual([(r["item"], r["action"]) for r in self.records()], [("venv", "install")])
        self.fake_uv("build")
        code, _, _ = self.run_json("-Install", "venv", "-Lang", "en")
        self.assertEqual(self.records(), [])

    def test_corrupt_record_file_is_treated_as_empty(self) -> None:
        self.record_file.parent.mkdir(parents=True)
        self.record_file.write_text("{ not json", encoding="utf-8")
        self.winget()
        code, out = self.run_setup("-RetryFailed", "-Lang", "en")
        self.assertIn("no recorded failure", out)
        self.assertEqual(self.winget_calls("install"), [])


class TestRetryFailed(PackagesCase):
    def seed(self, *records) -> None:
        self.record_file.parent.mkdir(parents=True, exist_ok=True)
        data = [{"time": "2026-09-30T10:00:00+09:00", "item": i, "action": a, "exit_code": 1,
                 "exit_hex": "", "class": "unknown", "message": "x"} for i, a in records]
        self.record_file.write_text(json.dumps({"schema": 1, "failures": data}), encoding="utf-8")

    def test_no_record_is_an_info_line_and_runs_nothing(self) -> None:
        self.winget()
        code, _, by_id = self.run_json("-RetryFailed", "-Lang", "en")
        self.assertEqual(by_id["retry"]["verdict"], "info")
        self.assertIn("no recorded failure", by_id["retry"]["detail"])
        self.assertEqual(self.winget_calls("install") + self.winget_calls("upgrade"), [])

    def test_only_recorded_items_are_retried_with_the_same_action(self) -> None:
        self.seed(("pwsh", "install"))
        self.fake_uv()
        self.winget(creates=["pwsh"])
        code, _, by_id = self.run_json("-RetryFailed", "-Lang", "en")
        installs = self.winget_calls("install")
        self.assertEqual(len(installs), 1, self.calls())
        self.assertIn("--id Microsoft.PowerShell", installs[0])
        self.assertIn("--accept-package-agreements", installs[0])  # allowed by the (re-asked) permission
        self.assertNotIn("astral-sh.uv", " ".join(installs))
        self.assertEqual(self.winget_calls("upgrade"), [])
        self.assertIn("pwsh install", by_id["retry"]["detail"])
        self.assertEqual(self.records(), [])  # succeeded: removed

    def test_update_and_reinstall_keep_their_own_command(self) -> None:
        self.seed(("pwsh", "update"), ("claude", "reinstall"))
        self.fake_pwsh("7.6.0")
        fakebin.make_fake(self.bin, "claude", "print('2.1.300 (Claude Code)')\n")
        self.winget()
        runner = self.fake_official_runner(0)
        self.run_setup("-RetryFailed", "-Lang", "en", env={"GATEKIT_SETUP_OFFICIAL_RUNNER": runner})
        self.assertEqual(len(self.winget_calls("upgrade")), 1, self.calls())
        self.assertEqual(self.winget_calls("install"), [])
        self.assertIn("official https://claude.ai/install.ps1", self.calls())

    def test_pwsh_reinstall_retry_uses_force(self) -> None:
        self.seed(("pwsh", "reinstall"))
        self.fake_pwsh("7.6.0")
        self.winget()
        self.run_setup("-RetryFailed", "-Lang", "en")
        installs = self.winget_calls("install")
        self.assertEqual(len(installs), 1)
        self.assertIn("--force", installs[0])

    def test_unknown_or_disallowed_records_are_ignored(self) -> None:
        self.seed(("foo", "install"), ("git", "reinstall"), ("pwsh", "explode"))
        self.winget()
        code, out = self.run_setup("-RetryFailed", "-Lang", "en")
        self.assertIn("no recorded failure", out)
        self.assertEqual(self.winget_calls("install") + self.winget_calls("upgrade"), [])

    def test_failed_retry_stays_recorded(self) -> None:
        self.seed(("pwsh", "install"))
        self.winget(install=0x8A150107)
        code, _, _ = self.run_json("-RetryFailed", "-Lang", "en")
        self.assertEqual(code, 4)
        self.assertEqual([(r["item"], r["class"]) for r in self.records()], [("pwsh", "network")])

    def test_retry_adds_to_explicit_names_without_duplicates(self) -> None:
        self.seed(("pwsh", "install"))
        self.fake_uv()
        self.winget(creates=["pwsh"])
        self.run_setup("-RetryFailed", "-Install", "pwsh", "-Lang", "en")
        self.assertEqual(len(self.winget_calls("install")), 1, self.calls())

    def test_status_cannot_be_combined_with_actions(self) -> None:
        self.winget()
        code, out = self.run_setup("-Status", "-RetryFailed", "-Lang", "en")
        self.assertEqual(code, 1, out)
        self.assertIn("refused", out)


class TestStatus(PackagesCase):
    def test_status_shows_the_table_and_skips_venv_config_and_doctor(self) -> None:
        self.fake_uv("build")
        self.fake_pwsh("7.6.1")
        self.winget({"astral-sh.uv": row("uv", "astral-sh.uv", "0.10.7")})
        code, _, by_id = self.run_json("-Status", "-Lang", "en")
        self.assertEqual(self.sync_calls(), [])
        self.assertFalse((self.kit / ".venv").exists())
        self.assertFalse((self.root / ".gatekit" / "config.json").exists())
        for key in ("P-pwsh", "P-uv", "P-claude", "P-git", "P-failures"):
            self.assertIn(key, by_id)
        self.assertIn("skips", by_id["S5"]["detail"])
        self.assertIn("skips", by_id["S15"]["detail"])
        self.assertNotIn("S12-config", by_id)

    def test_status_shows_recorded_failures(self) -> None:
        self.winget(install=0x8A15003A)
        self.run_setup("-Install", "pwsh", "-Lang", "en")
        self.fake_uv()
        _, _, by_id = self.run_json("-Status", "-Lang", "en")
        self.assertIn("pwsh install", by_id["P-failures"]["detail"])
        self.assertIn("policy", by_id["P-failures"]["detail"])


if __name__ == "__main__":
    unittest.main()
