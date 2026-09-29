"""Tests for gatekit.paths — project root and state directory resolution."""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import paths


class TempProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # realpath: macOS /var -> /private/var symlink would break comparisons.
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestProjectRoot(TempProject):
    def test_finds_ancestor_with_gatekit_dir(self) -> None:
        (self.root / ".gatekit").mkdir()
        deep = self.root / "src" / "auth" / "nested"
        deep.mkdir(parents=True)
        self.assertEqual(paths.project_root(str(deep)), self.root)

    def test_finds_ancestor_with_git_dir(self) -> None:
        (self.root / ".git").mkdir()
        deep = self.root / "a" / "b"
        deep.mkdir(parents=True)
        self.assertEqual(paths.project_root(str(deep)), self.root)

    def test_gatekit_marker_wins_over_higher_git(self) -> None:
        (self.root / ".git").mkdir()
        inner = self.root / "packages" / "app"
        inner.mkdir(parents=True)
        (inner / ".gatekit").mkdir()
        self.assertEqual(paths.project_root(str(inner)), inner)

    def test_falls_back_to_cwd_when_no_marker(self) -> None:
        deep = self.root / "no" / "markers"
        deep.mkdir(parents=True)
        self.assertEqual(paths.project_root(str(deep)), deep)

    def test_none_uses_process_cwd(self) -> None:
        (self.root / ".gatekit").mkdir()
        previous = os.getcwd()
        os.chdir(self.root)
        try:
            self.assertEqual(paths.project_root(None), self.root)
        finally:
            os.chdir(previous)

    def test_nonexistent_cwd_does_not_raise(self) -> None:
        missing = self.root / "gone"
        self.assertIsInstance(paths.project_root(str(missing)), pathlib.Path)


class TestDerivedDirs(TempProject):
    def test_state_dir(self) -> None:
        self.assertEqual(paths.state_dir(self.root), self.root / ".gatekit")

    def test_spec_dir(self) -> None:
        self.assertEqual(paths.spec_dir(self.root), self.root / "spec")

    def test_runs_dir_and_hook_error_log(self) -> None:
        self.assertEqual(paths.runs_dir(self.root), self.root / ".gatekit" / "runs")
        self.assertEqual(
            paths.hook_error_log(self.root),
            self.root / ".gatekit" / "runs" / "hook-errors.log",
        )

    def test_jobs_dir(self) -> None:
        self.assertEqual(paths.jobs_dir(self.root), self.root / ".gatekit" / "jobs")

    def test_gatekit_root_contains_bin_gatekit(self) -> None:
        found = paths.gatekit_root()
        self.assertTrue((found / "bin" / "gatekit").is_file())
        self.assertTrue((found / "bin" / "gatekit.py").is_file())

    def test_gatekit_root_is_derived_from_file_not_env(self) -> None:
        # Standalone mode has no plugin manager, so CLAUDE_PLUGIN_ROOT must
        # not influence the result.
        previous = os.environ.get("CLAUDE_PLUGIN_ROOT")
        os.environ["CLAUDE_PLUGIN_ROOT"] = str(self.root)
        try:
            found = paths.gatekit_root()
        finally:
            if previous is None:
                os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            else:
                os.environ["CLAUDE_PLUGIN_ROOT"] = previous
        self.assertNotEqual(found, self.root)
        self.assertTrue((found / "bin" / "gatekit.py").is_file())

    def test_ensure_dir_is_idempotent(self) -> None:
        target = self.root / "x" / "y"
        paths.ensure_dir(target)
        paths.ensure_dir(target)
        self.assertTrue(target.is_dir())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
