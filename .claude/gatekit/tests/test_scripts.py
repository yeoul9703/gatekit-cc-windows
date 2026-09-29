"""scripts/*.ps1 must stay Windows PowerShell 5.1 compatible, and setup.ps1
must stop with exit code 2 (printing install commands only) when uv is absent."""
from __future__ import annotations

import os
import pathlib
import subprocess
import unittest

KIT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = KIT / "scripts"
POWERSHELL = pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) / \
    "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"


class TestScriptFiles(unittest.TestCase):
    def test_expected_scripts_exist(self) -> None:
        for name in ("session-check.ps1", "setup.ps1", "verify.ps1"):
            self.assertTrue((SCRIPTS / name).is_file(), name)

    def test_powershell_5_1_compatible_and_read_as_utf8(self) -> None:
        for path in sorted(SCRIPTS.glob("*.ps1")):
            raw = path.read_bytes()
            # BOM: Windows PowerShell 5.1 decodes BOM-less files as the ANSI
            # code page, which would mangle the Korean messages.
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "%s needs a UTF-8 BOM" % path.name)
            text = raw.decode("utf-8-sig")
            for banned in ("&&", "||", "?:", "??", "?."):
                self.assertNotIn(banned, text, "%s uses %r (PowerShell 7 only)" % (path.name, banned))


class TestSetupWithoutUv(unittest.TestCase):
    def test_missing_uv_prints_install_commands_and_exits_2(self) -> None:
        env = {"SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
               "PATH": str(POWERSHELL.parent), "PATHEXT": ".EXE;.CMD"}
        proc = subprocess.run(
            [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             str(SCRIPTS / "setup.ps1")],
            capture_output=True, env=env, timeout=60)
        out = proc.stdout.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 2, out + proc.stderr.decode("utf-8", "replace"))
        self.assertIn("winget install --id=astral-sh.uv -e", out)
        self.assertIn("https://astral.sh/uv/install.ps1", out)
        self.assertIn("[fail]", out)


if __name__ == "__main__":
    unittest.main()
