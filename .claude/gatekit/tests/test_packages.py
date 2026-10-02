"""scripts/packages.json is the single source for the programs setup.ps1 manages."""
from __future__ import annotations

import json
import re
import unittest

from tests import fakebin
from tests.test_scripts import POWERSHELL, SCRIPTS, SetupCase

PACKAGES = SCRIPTS / "packages.json"
FIELDS = ("key", "name_ko", "winget_id", "level", "min_version", "installer_type",
          "admin_may_be_required", "official_script_url", "docs_url")


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

    def test_the_four_managed_packages_have_every_field(self) -> None:
        packages = {p["key"]: p for p in load()["packages"]}
        self.assertEqual(sorted(packages), ["claude", "git", "pwsh", "uv"])
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

    def test_levels_and_special_values(self) -> None:
        packages = {p["key"]: p for p in load()["packages"]}
        self.assertEqual(packages["uv"]["level"], "필수")
        self.assertEqual(packages["claude"]["level"], "필수")
        self.assertEqual(packages["pwsh"]["level"], "필수")
        self.assertEqual(packages["git"]["level"], "선택")
        self.assertEqual(packages["pwsh"]["installer_type"], "msix")
        self.assertIsNone(packages["git"]["official_script_url"])

    def test_setup_ps1_hard_codes_none_of_the_ids_or_urls(self) -> None:
        text = (SCRIPTS / "setup.ps1").read_bytes().decode("utf-8-sig")
        for pkg in load()["packages"]:
            self.assertNotIn(pkg["winget_id"], text, pkg["key"])
            for field in ("official_script_url", "docs_url", "min_version"):
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
        self.assertIn("9.0.0", by_id["S6"]["detail"])


if __name__ == "__main__":
    unittest.main()
