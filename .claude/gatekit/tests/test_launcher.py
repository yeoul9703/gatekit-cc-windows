"""The bin/gatekit.py launcher must work from a foreign cwd with no PYTHONPATH."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[1]
LAUNCHER = PLUGIN_ROOT / "bin" / "gatekit.py"


class TestLauncher(unittest.TestCase):
    def _run(self, args, cwd):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        return subprocess.run([sys.executable, str(LAUNCHER), *args], cwd=cwd,
                              capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)

    def test_lang_from_foreign_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run(["lang", "안녕하세요 기획서 만들어줘"], tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ko")

    def test_root_defaults_to_cwd_project_not_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / ".gatekit").mkdir()
            proc = self._run(["spec", "validate", "--json"], tmp)
            self.assertIn(proc.returncode, (0, 1), proc.stderr)
            # The report must be about the temp project, not the plugin's own tree.
            self.assertNotIn(str(PLUGIN_ROOT), proc.stdout)

    def test_unknown_subcommand_exit_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run(["nope"], tmp)
        self.assertEqual(proc.returncode, 2)
