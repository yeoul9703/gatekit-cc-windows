"""scripts/packages.json is the single source for the programs setup.ps1 manages."""
from __future__ import annotations

import json
import re
import unittest

from tests import fakebin
from tests.test_scripts import POWERSHELL, SCRIPTS, SetupCase

PACKAGES = SCRIPTS / "packages.json"
FIELDS = ("key", "name_ko", "winget_id", "level", "min_version", "installer_type",
          "admin_may_be_required", "official_script_url", "docs_url",
          "appx_name", "appx_preview_name", "store_url")


def load() -> dict:
    return json.loads(PACKAGES.read_text(encoding="utf-8"))


class TestPackagesFile(unittest.TestCase):
    def test_file_is_utf8_without_bom_and_valid_json(self) -> None:
        raw = PACKAGES.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        raw.decode("utf-8")
        self.assertEqual(load()["schema"], 1)

    def test_python_min_matches_python_version_and_pyproject(self) -> None:
        wanted = load()["python_min"]
        self.assertRegex(wanted, r"^\d+\.\d+$")
        kit = PACKAGES.parent.parent
        self.assertEqual((kit / ".python-version").read_text(encoding="utf-8").strip(), wanted)
        self.assertIn('requires-python = ">=%s"' % wanted,
                      (kit / "pyproject.toml").read_text(encoding="utf-8"))

    def test_the_file_holds_every_key_setup_reads_and_setup_installs_every_entry(self) -> None:
        # Not a count: an entry may be added or taken out. What must hold is that setup.ps1 finds
        # every key it reads, and that every entry is a name -Install accepts.
        keys = [p["key"] for p in load()["packages"]]
        self.assertEqual(len(keys), len(set(keys)), keys)
        text = (SCRIPTS / "setup.ps1").read_bytes().decode("utf-8-sig")
        needed = re.search(r"\$pkgKeysNeeded = @\(([^)]*)\)", text)
        allowed = re.search(r"\$allowed = @\(([^)]*)\)", text)
        assert needed is not None and allowed is not None
        needed_keys = re.findall(r"'(\w+)'", needed.group(1))
        self.assertTrue(needed_keys)
        for key in needed_keys:
            self.assertIn(key, keys, "setup.ps1 reads packages.json entry %r" % key)
        for key in keys:
            self.assertIn(key, re.findall(r"'(\w+)'", allowed.group(1)), key)
        for key in re.findall(r"\$script:pkgs\['(\w+)'\]", text):
            self.assertIn(key, needed_keys, "setup.ps1 reads %r without checking that it is there" % key)
        self.assertNotRegex(text, r"\$script:pkgs\.Count")  # the count that broke on an added entry

    def test_every_managed_package_has_every_field(self) -> None:
        packages = {p["key"]: p for p in load()["packages"]}
        for key, pkg in packages.items():
            self.assertEqual(sorted(pkg), sorted(FIELDS), key)
            self.assertRegex(pkg["winget_id"], r"^[A-Za-z0-9]+[.-][A-Za-z0-9.-]+$")
            self.assertIn(pkg["level"], ("필수", "권장", "선택"))
            self.assertTrue(pkg["name_ko"])
            self.assertIsInstance(pkg["admin_may_be_required"], bool)
            self.assertTrue(pkg["docs_url"].startswith("https://"))
            if pkg["min_version"] is not None:
                self.assertRegex(pkg["min_version"], r"^\d+\.\d+\.\d+$")
            if pkg["official_script_url"] is not None:
                self.assertTrue(pkg["official_script_url"].endswith("install.ps1"))
            for field in ("appx_name", "appx_preview_name"):
                if pkg[field] is not None:
                    self.assertRegex(pkg[field], r"^[A-Za-z0-9]+(\.[A-Za-z0-9]+)+$")
            if pkg["store_url"] is not None:
                self.assertTrue(pkg["store_url"].startswith("https://apps.microsoft.com/"))

    def test_levels_and_special_values(self) -> None:
        packages = {p["key"]: p for p in load()["packages"]}
        self.assertEqual(packages["uv"]["level"], "필수")
        self.assertEqual(packages["claude"]["level"], "권장")  # nothing runs it by default
        self.assertEqual(packages["pwsh"]["level"], "필수")
        self.assertEqual(packages["git"]["level"], "권장")  # gatekit runs without it; setup offers it
        self.assertEqual(packages["pwsh"]["installer_type"], "msix")
        self.assertIsNone(packages["git"]["official_script_url"])  # winget only
        self.assertTrue(packages["git"]["admin_may_be_required"])  # only when the user scope fails
        self.assertEqual(packages["winget"]["level"], "권장")
        self.assertFalse(packages["winget"]["admin_may_be_required"])
        self.assertEqual(packages["node"]["level"], "선택")  # for what the user builds, not for gatekit
        self.assertIsNone(packages["node"]["official_script_url"])  # winget only, like git
        self.assertTrue(packages["node"]["admin_may_be_required"])  # only when the user scope fails
        self.assertIsNotNone(packages["node"]["min_version"])  # what the Playwright test runner accepts

    def test_product_names_that_tell_stable_from_preview(self) -> None:
        # The stable PowerShell 7 and the preview build are different Windows packages.
        packages = {p["key"]: p for p in load()["packages"]}
        self.assertEqual(packages["pwsh"]["appx_name"], "Microsoft.PowerShell")
        self.assertEqual(packages["pwsh"]["appx_preview_name"], "Microsoft.PowerShellPreview")
        self.assertEqual(packages["winget"]["appx_name"], "Microsoft.DesktopAppInstaller")
        self.assertEqual(packages["winget"]["store_url"], "https://apps.microsoft.com/detail/9nblggh4nns1")
        for key in ("uv", "claude", "git", "node"):
            self.assertIsNone(packages[key]["appx_name"], key)

    def test_setup_ps1_hard_codes_none_of_the_ids_or_urls(self) -> None:
        text = (SCRIPTS / "setup.ps1").read_bytes().decode("utf-8-sig")
        for pkg in load()["packages"]:
            self.assertNotIn(pkg["winget_id"], text, pkg["key"])
            for field in ("official_script_url", "docs_url", "min_version", "appx_name",
                          "appx_preview_name", "store_url"):
                if pkg[field]:
                    self.assertNotIn(pkg[field], text, "%s %s" % (pkg["key"], field))
        self.assertIn("packages.json", text)

    def test_no_script_other_than_setup_needs_the_ids(self) -> None:
        # session-check must stay free of winget (no network call at session start).
        text = (SCRIPTS / "session-check.ps1").read_bytes().decode("utf-8-sig")
        self.assertNotRegex(text, re.compile(r"winget\s+(install|upgrade|list)"))


@unittest.skipUnless(POWERSHELL.is_file(), "Windows PowerShell 5.1 not available")
class TestSetupReadsPackages(SetupCase):
    def edit(self, key: str, **changes) -> None:
        path = self.kit / "scripts" / "packages.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for pkg in data["packages"]:
            if pkg["key"] == key:
                pkg.update(changes)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def installs(self) -> list:
        return [c for c in self.calls() if c.startswith("winget install")]

    def test_winget_id_and_installer_type_come_from_the_file(self) -> None:
        self.edit("pwsh", winget_id="Test.Pwsh", installer_type="msi")
        self.fake_winget(0)
        self.run_setup("-Install", "pwsh", "-Lang", "en")
        call = self.installs()[0]
        self.assertIn("--id Test.Pwsh", call)
        self.assertIn("--installer-type msi", call)
        self.assertNotIn("Microsoft.PowerShell", call)

    def test_uv_id_and_official_url_come_from_the_file(self) -> None:
        self.edit("uv", winget_id="Test.Uv", official_script_url="https://example.test/uv.ps1")
        self.fake_winget(0x8A15003A)  # policy block: the official script is the fallback
        runner = self.fake_official_runner(0)
        self.run_setup("-Install", "uv", "-Lang", "en", env={"GATEKIT_SETUP_OFFICIAL_RUNNER": runner})
        self.assertIn("--id Test.Uv", self.installs()[0])
        self.assertIn("official https://example.test/uv.ps1", self.calls())

    def test_missing_packages_file_fails_with_exit_1(self) -> None:
        (self.kit / "scripts" / "packages.json").unlink()
        code, out = self.run_setup("-Lang", "en")
        self.assertEqual(code, 1, out)
        self.assertIn("packages.json", out)

    def test_an_added_entry_changes_nothing_and_a_missing_one_is_named(self) -> None:
        path = self.kit / "scripts" / "packages.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        extra = dict(data["packages"][-1], key="extra", winget_id="Test.Extra")
        data["packages"].append(extra)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        code, _, by_id = self.run_json("-Status", "-Lang", "en")
        self.assertNotIn("args", by_id)  # the file was read: no "could not read packages.json"
        self.assertNotEqual(code, 1, by_id)
        self.assertIn("P-uv", by_id)  # and the package table is still there
        self.assertNotIn("P-extra", by_id)
        data["packages"] = [p for p in data["packages"] if p["key"] not in ("git", "node")]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        code, _, by_id = self.run_json("-Status", "-Lang", "en")
        self.assertEqual(code, 1, by_id)
        self.assertEqual(by_id["args"]["verdict"], "fail")
        self.assertIn("missing entries: git, node", by_id["args"]["detail"])
        self.assertIn(".claude/gatekit/scripts/packages.json", by_id["args"]["action"])

    def test_minimum_versions_come_from_the_file(self) -> None:
        self.edit("uv", min_version="99.0.0")
        self.fake_uv()
        code, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["S4"]["verdict"], "fail")
        self.assertIn("99.0.0", by_id["S4"]["detail"])

    def test_claude_recommended_version_comes_from_the_file(self) -> None:
        self.edit("claude", min_version="9.0.0")
        fakebin.make_fake(self.bin, "claude", "print('2.1.300 (Claude Code)')\n")
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["S6"]["verdict"], "warn")
        self.assertEqual(by_id["S6"]["level"], "recommended")
        self.assertIn("9.0.0", by_id["S6"]["detail"])

    def test_node_id_and_minimum_come_from_the_file(self) -> None:
        self.edit("node", winget_id="Test.Node", min_version="99.0.0")
        fakebin.make_fake(self.bin, "node", "print('v24.19.0')\n")
        fakebin.make_fake(self.bin, "npm", "print('11.6.0')\n")
        _, _, by_id = self.run_json("-Status", "-Lang", "en")
        self.assertEqual(by_id["S18"]["verdict"], "info", by_id["S18"])
        self.assertIn("24.19.0 < 99.0.0", by_id["S18"]["detail"])
        (self.bin / "node.cmd").unlink()
        self.fake_winget(0)
        self.run_setup("-Install", "node", "-Lang", "en")
        self.assertIn("--id Test.Node", self.installs()[0])
        self.assertNotIn("OpenJS", " ".join(self.calls()))

    def test_the_package_row_level_comes_from_the_file(self) -> None:
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["P-claude"]["level"], "recommended")
        self.assertEqual(by_id["P-uv"]["level"], "required")
        self.assertEqual(by_id["P-node"]["level"], "info")  # 선택
        self.edit("claude", level="필수")
        _, _, by_id = self.run_json("-Lang", "en")
        self.assertEqual(by_id["P-claude"]["level"], "required")


if __name__ == "__main__":
    unittest.main()
