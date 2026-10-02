"""docs/SETUP-REFERENCE.md must agree with scripts/packages.json and scripts/setup.ps1,
and USAGE and README must point to it. (What the setup skill itself says is checked in
test_command_docs.py.)"""
from __future__ import annotations

import json
import pathlib
import re
import unittest

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

    def test_the_claude_command_is_recommended_and_the_exit_codes_say_so(self) -> None:
        claude = next(p for p in PACKAGES if p["key"] == "claude")
        self.assertEqual(claude["level"], "권장")
        text = doc_text()
        self.assertIn("### 2-3. Claude Code (`claude` 명령, 권장)", text)
        section = text[text.index("### 2-3. "):text.index("### 2-3-1. ")]
        rows = {r[0]: r for r in table_rows("### 2-3. ", section) if len(r) == 3 and "종료 코드" in r[1]}
        self.assertIn("`fail`(필수), 종료 코드 2, `-Install claude`", rows["이 창의 PATH에 없음"][2])
        self.assertEqual(rows["이 창의 PATH에 없음"][1], "`warn`(권장), 종료 코드에 영향 없음")
        self.assertIn("종료 코드 3", rows["설치돼 있지만 이 창의 PATH에 안 보임"][2])
        self.assertIn(claude["min_version"], section)
        for key in ('`build.execution`이 `"worker"`', "`verify.evaluator`에 `agent`가 아닌"):
            self.assertIn(key, section)
        self.assertNotIn("데스크톱 앱만으로는", text)
        usage = (DOC.parent / "USAGE.md").read_text(encoding="utf-8")
        self.assertIn("| Claude Code | 예 | 데스크톱 앱, VS Code 확장, 터미널 중 어느 것이든 됩니다 |", usage)
        self.assertRegex(usage, r"(?m)^\| `claude` 명령\(CLI\) \| 선택 \|")
        self.assertNotIn("데스크톱 앱만으로는", usage)

    def test_git_is_recommended_and_installed_in_the_user_scope_first(self) -> None:
        git = next(p for p in PACKAGES if p["key"] == "git")
        self.assertEqual(git["level"], "권장")
        text = doc_text()
        self.assertIn("### 2-4. Git for Windows (`git`, 권장)", text)
        section = text[text.index("### 2-4. "):text.index("## 3. ")]
        # the documented command is the one the script prints and runs: the user scope first
        user_scope = "winget install --id %s -e --source winget --scope user" % git["winget_id"]
        self.assertIn("| 설치 | `%s` |" % user_scope, section)
        self.assertIn("`winget install --id %s -e --source winget` (또는 %s"
                      % (git["winget_id"], git["docs_url"]), section)
        ps1 = ps1_text()
        self.assertIn("' -e --source winget --scope user'", ps1)
        self.assertIn("@('--scope', 'user')", ps1)
        # S7 and the order of -Install git
        for phrase in ("| 없음 | `warn`(권장), 종료 코드에 영향 없음 | `-Install git` (winget도 없으면 `-Install winget,git`) |",
                       "| 1 | 사용자 범위로 설치(`--scope user`) | 아니오 |",
                       "관리자 확인 창(UAC)이 뜰 수 있고 다른 창 뒤에 숨을 수 있다",
                       "`S10-git`", "`S16-git`"):
            self.assertIn(phrase, section)
        # no elevation tool, with the reason in one line
        self.assertIn("gsudo 같은 권한 상승 도구는 쓰지 않습니다. gsudo도 같은 관리자 확인 창을 띄울 뿐이고",
                      " ".join(section.split()))
        self.assertNotIn("gsudo", ps1)
        self.assertNotIn("자동으로 설치·업데이트·재설치하지 않고", text)  # the older wording
        usage = (DOC.parent / "USAGE.md").read_text(encoding="utf-8")
        self.assertRegex(usage, r"(?m)^\| Git for Windows \| 권장 \|")
        self.assertIn("관리자 확인 창이 뜰 수 있습니다", usage)

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

    def test_every_script_switch_has_one_row_in_the_table(self) -> None:
        rows = table_rows("## 3. setup 스위치", doc_text())
        for switch in ("-Install", "-Update", "-Reinstall", "-RetryFailed", "-Status", "-Json", "-Lang"):
            hit = [r for r in rows if r[1].startswith("`" + switch)]
            self.assertEqual(len(hit), 1, switch)


class TestExitCodesAndWinget(unittest.TestCase):
    def test_exit_code_table_lists_0_to_4(self) -> None:
        rows = table_rows("## 4. 종료 코드", doc_text())
        self.assertEqual([r[0] for r in rows], ["0", "1", "2", "3", "4"])
        text = ps1_text()
        for code in "01234":
            self.assertRegex(text, r"#\s+%s\s" % code)
        self.assertIn("1 > 4 > 3 > 2 > 0", doc_text())

    def test_exit_code_3_says_how_to_quit_the_desktop_app(self) -> None:
        # One sentence everywhere: the reopen advice, then where to quit the desktop app.
        reopen = "Claude Code(데스크톱 앱, VS Code 창, 또는 실행 중인 터미널)를 완전히 닫고 다시 "
        tray = "데스크톱 앱은 창을 닫아도 남아 있으니 작업 표시줄 오른쪽 아래(트레이)의 Claude 아이콘에서 종료"
        rows = {r[0]: r for r in table_rows("## 4. 종료 코드", doc_text())}
        self.assertIn(reopen + "열기. " + tray, rows["3"][2])
        self.assertEqual(" ".join(doc_text().split()).count(tray), 2)  # the intro and the table
        self.assertIn(reopen + "여세요. " + tray + "하세요'", ps1_text())
        self.assertEqual(ps1_text().count("완전히 닫고 다시"), 1)  # Get-ReopenAdvice only
        session = (KIT / "scripts" / "session-check.ps1").read_bytes().decode("utf-8-sig")
        self.assertIn(tray + "하세요.'", session)
        self.assertEqual(session.count(reopen + "여세요'"), 1)
        usage = " ".join((DOC.parent / "USAGE.md").read_text(encoding="utf-8").split())
        self.assertEqual(usage.count("데스크톱 앱은 창을 닫아도 남아 있으니 작업 표시줄 오른쪽 아래(트레이)의 Claude 아이콘에서 종료"), 2)

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
