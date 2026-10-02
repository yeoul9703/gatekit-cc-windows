"""docs/SETUP-REFERENCE.md must agree with scripts/packages.json and scripts/setup.ps1,
and USAGE and README must point to it. (What the setup skill itself says is checked in
test_command_docs.py.)"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

from gatekit import setup as setup_cli

KIT = pathlib.Path(__file__).resolve().parents[1]
PROJECT = KIT.parents[1]
DOC = PROJECT / "docs" / "SETUP-REFERENCE.md"
SETUP_PS1 = KIT / "scripts" / "setup.ps1"
PACKAGES = json.loads((KIT / "scripts" / "packages.json").read_text(encoding="utf-8"))["packages"]


def doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def ps1_text() -> str:
    return SETUP_PS1.read_bytes().decode("utf-8-sig")


def table_rows(section_start: str, text: str) -> list:
    """Cells of every table row after *section_start* up to the next heading."""
    start = text.index(section_start)
    end = text.find("\n## ", start + 1)
    body = text[start:end if end != -1 else len(text)]
    rows = []
    for line in body.splitlines():
        if line.startswith("|") and not re.match(r"^\|[-| ]+\|$", line):
            rows.append([c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))])
    return rows[1:]  # without the header row


class TestPackagesTable(unittest.TestCase):
    def test_every_package_row_matches_packages_json(self) -> None:
        rows = {r[0].strip("`"): r for r in table_rows("## 1. 관리 대상 프로그램", doc_text())}
        self.assertEqual(sorted(rows), sorted(p["key"] for p in PACKAGES))
        for pkg in PACKAGES:
            row = rows[pkg["key"]]
            self.assertEqual(row[1], pkg["name_ko"], pkg["key"])
            self.assertEqual(row[2], "`%s`" % pkg["winget_id"], pkg["key"])
            self.assertEqual(row[3], pkg["level"], pkg["key"])
            self.assertEqual(row[4], pkg["min_version"] or "-", pkg["key"])
            self.assertEqual(row[5], pkg["installer_type"] or "-", pkg["key"])
            self.assertEqual(row[7], pkg["official_script_url"] or "없음", pkg["key"])
            self.assertEqual(row[8], pkg["docs_url"], pkg["key"])
            self.assertEqual(pkg["admin_may_be_required"], row[6] not in ("아니오",), pkg["key"])

    def test_every_winget_id_in_a_command_is_a_managed_package(self) -> None:
        ids = {p["winget_id"] for p in PACKAGES}
        used = set(re.findall(r"winget (?:install|upgrade|list) --id[= ]([A-Za-z0-9.-]+)", doc_text()))
        self.assertEqual(used, ids)

    def test_every_official_script_url_matches(self) -> None:
        urls = {p["official_script_url"] for p in PACKAGES if p["official_script_url"]}
        used = set(re.findall(r"irm (https://\S+?install\.ps1)", doc_text()))
        self.assertEqual(used, urls)

    def test_installer_type_is_in_the_pwsh_commands(self) -> None:
        pwsh = next(p for p in PACKAGES if p["key"] == "pwsh")
        text = doc_text()
        for verb in ("install", "upgrade"):
            self.assertRegex(text, r"winget %s --id %s -e .*--installer-type %s"
                             % (verb, re.escape(pwsh["winget_id"]), pwsh["installer_type"]))
        self.assertIn("--installer-type msix --force", text)

    def test_reinstall_names_match_the_script(self) -> None:
        match = re.search(r"\$allowedReinstall = @\(([^)]*)\)", ps1_text())
        assert match is not None
        names = re.findall(r"'(\w+)'", match.group(1))
        self.assertEqual(sorted(names), ["claude", "pwsh", "uv"])
        self.assertIn("`-Reinstall uv,pwsh,claude`", doc_text())

    def test_install_names_match_the_script(self) -> None:
        match = re.search(r"\$allowed = @\(([^)]*)\)", ps1_text())
        assert match is not None
        names = re.findall(r"'(\w+)'", match.group(1))
        self.assertEqual(names, ["winget", "pwsh", "uv", "claude", "git", "venv"])
        self.assertIn("`-Install %s`" % ",".join(names), doc_text())

    def test_winget_install_section_names_both_steps_and_the_store(self) -> None:
        text = doc_text()
        winget = next(p for p in PACKAGES if p["key"] == "winget")
        self.assertIn("Add-AppxPackage -RegisterByFamilyName -MainPackage %s_8wekyb3d8bbwe"
                      % winget["appx_name"], text)
        self.assertIn("Install-Module -Name Microsoft.WinGet.Client -Scope CurrentUser", text)
        self.assertIn("Repair-WinGetPackageManager", text)
        self.assertIn(winget["store_url"], text)

    def test_stable_and_preview_product_names_are_documented(self) -> None:
        text = doc_text()
        pwsh = next(p for p in PACKAGES if p["key"] == "pwsh")
        self.assertIn("`%s`" % pwsh["appx_name"], text)
        self.assertIn("`%s`" % pwsh["appx_preview_name"], text)


class TestSwitchTables(unittest.TestCase):
    def test_every_script_switch_is_documented(self) -> None:
        params = re.search(r"param\((.*?)\n\)", ps1_text(), re.S)
        assert params is not None
        names = re.findall(r"\$(\w+)\s*(?:=|,|\n|$)", params.group(1))
        self.assertEqual(sorted(names), sorted(["Install", "Update", "Reinstall", "RetryFailed", "Status", "Json", "Lang"]))
        text = doc_text()
        for name in names:
            self.assertIn("`-%s" % name, text, name)

    def test_every_cli_flag_is_documented(self) -> None:
        text = doc_text()
        flags = [a for a in setup_cli._parser()._option_string_actions if a.startswith("--") and a != "--help"]
        self.assertGreaterEqual(len(flags), 7)
        for flag in flags:
            self.assertIn("`%s" % flag, text, flag)

    def test_cli_and_script_forms_correspond_row_by_row(self) -> None:
        pairs = {"-Install": "--install", "-Update": "--update", "-Reinstall": "--reinstall",
                 "-RetryFailed": "--retry-failed", "-Status": "--status", "-Json": "--json", "-Lang": "--lang"}
        rows = table_rows("## 3. setup 스위치와 CLI 대응표", doc_text())
        for script_flag, cli_flag in pairs.items():
            hit = [r for r in rows if r[1].startswith("`" + script_flag)]
            self.assertEqual(len(hit), 1, script_flag)
            self.assertTrue(hit[0][2].startswith("`" + cli_flag), (script_flag, hit[0]))
        built = setup_cli.build_command("PS", pathlib.Path("S"), setup_cli._parser().parse_args(
            ["--retry-failed", "--status", "--json", "--lang", "ko"]))
        self.assertEqual(built[6:], ["-RetryFailed", "-Status", "-Json", "-Lang", "ko"])


class TestExitCodesAndWinget(unittest.TestCase):
    def test_exit_code_table_lists_0_to_4(self) -> None:
        rows = table_rows("## 4. 종료 코드", doc_text())
        self.assertEqual([r[0] for r in rows], ["0", "1", "2", "3", "4"])
        text = ps1_text()
        for code in "01234":
            self.assertRegex(text, r"#\s+%s\s" % code)
        self.assertIn("1 > 4 > 3 > 2 > 0", doc_text())

    def test_winget_code_table_equals_the_script_table(self) -> None:
        script = {}
        for line in ps1_text().splitlines():
            m = re.match(r"\s*'([0-9A-F]{8})' \{ return (.*)$", line)
            if not m:
                continue
            hex_code, rest = m.groups()
            if "New-PolicyFailure" in rest:
                script[hex_code] = "policy"
            elif "New-AgreementFailure" in rest:
                script[hex_code] = "agreement"
            else:
                cls = re.search(r"cls = '(\w+)'", rest)
                assert cls is not None
                script[hex_code] = cls.group(1)
        self.assertGreaterEqual(len(script), 11)
        rows = {r[0].strip("`"): r for r in table_rows("## 6. 자주 나오는 winget 오류 코드", doc_text())}
        self.assertEqual(sorted(rows), sorted("0x" + h for h in script))
        expect = {"policy": "종료 코드 4", "network": "종료 코드 4", "agreement": "종료 코드 2",
                  "reboot": "종료 코드 3", "ok": "성공으로 처리"}
        for hex_code, cls in script.items():
            self.assertIn(expect[cls], rows["0x" + hex_code][2], (hex_code, cls))

    def test_it_message_matches_the_scripts_wording(self) -> None:
        self.assertIn("조직 정책(AppLocker/Intune)이나 프록시·방화벽이 winget, astral.sh, claude.ai 접속을", doc_text())
        self.assertIn("조직 정책(AppLocker/Intune)이나 프록시·방화벽이 winget, astral.sh, claude.ai 접속을", ps1_text())


class TestLinks(unittest.TestCase):
    def test_pointers_to_the_reference(self) -> None:
        self.assertIn("SETUP-REFERENCE.md", (PROJECT / "docs" / "USAGE.md").read_text(encoding="utf-8"))
        self.assertIn("docs/SETUP-REFERENCE.md", (PROJECT / "README.md").read_text(encoding="utf-8"))

    def test_the_direct_script_fallback_is_documented(self) -> None:
        text = doc_text()
        self.assertIn("## 9. CLI가 안 될 때", text)
        self.assertIn("-NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1", text)


if __name__ == "__main__":
    unittest.main()
