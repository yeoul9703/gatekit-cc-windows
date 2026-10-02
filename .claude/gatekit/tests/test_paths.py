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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fakebin import make_fake, print_and_exit  # noqa: E402


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

    def test_gatekit_root_contains_launcher_and_no_sh_wrapper(self) -> None:
        found = paths.gatekit_root()
        self.assertTrue((found / "bin" / "gatekit.py").is_file())
        # The POSIX sh wrapper is gone: hooks and commands go through uv/venv python.
        self.assertFalse((found / "bin" / "gatekit").exists())

    def test_skills_root_is_the_sibling_of_the_gatekit_root(self) -> None:
        self.assertEqual(paths.skills_root(), paths.gatekit_root().parent / "skills")
        self.assertEqual(paths.skill_dir("build"), paths.skills_root() / "gatekit-build")
        self.assertTrue((paths.skill_dir("build") / "SKILL.md").is_file())
        # The engine's own data files live in the shared folder.
        shared = paths.skill_dir("shared") / "assets"
        self.assertTrue((shared / "heading-map.json").is_file())
        self.assertTrue((shared / "presets" / "design").is_dir())

    def test_cli_invocation_is_shell_neutral_uv_form(self) -> None:
        inv = paths.cli_invocation()
        self.assertEqual(
            inv,
            "uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py")
        # Pastes unchanged into PowerShell and Git Bash: no quotes, no $VAR,
        # no backslashes, no absolute (personal) path.
        for bad in ('"', "'", "$", "\\", "C:", str(paths.gatekit_root())):
            self.assertNotIn(bad, inv)
        self.assertIn(inv, paths.CLI_INVOCATION)

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


class TestResolveArgv(TempProject):
    def test_a_bare_command_that_is_only_a_cmd_shim_can_be_run(self) -> None:
        """`subprocess` without a shell skips PATHEXT on Windows, so a bare
        `claude`/`npm` that is really `claude.cmd` must be resolved first."""
        import subprocess

        make_fake(self.root, "faketool", print_and_exit("tool 9.9"))
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = str(self.root) + os.pathsep + old
        try:
            argv = paths.resolve_argv(["faketool", "--version"])
            proc = subprocess.run(argv, stdout=subprocess.PIPE)
        finally:
            os.environ["PATH"] = old
        self.assertEqual(proc.returncode, 0)
        self.assertIn(b"tool 9.9", proc.stdout)

    def test_unknown_command_and_explicit_paths_are_left_alone(self) -> None:
        self.assertEqual(paths.resolve_argv(["no-such-command-xyz", "1"]), ["no-such-command-xyz", "1"])
        explicit = os.path.join("some", "dir", "tool")
        self.assertEqual(paths.resolve_argv([explicit, 2]), [explicit, "2"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
