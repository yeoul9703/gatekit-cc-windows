"""The command docs and skill shims must run unchanged in PowerShell and Git
Bash: one uv-based invocation form, no bash-only syntax, PowerShell allowed."""
from __future__ import annotations

import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gatekit import cli, paths  # noqa: E402

PROJECT = pathlib.Path(__file__).resolve().parents[3]
COMMANDS = sorted((PROJECT / ".claude" / "commands" / "gatekit").glob("*.md"))
SKILLS = sorted((PROJECT / ".claude" / "skills").glob("gatekit-*/SKILL.md"))
CLI = paths.cli_invocation()


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class TestCommandDocs(unittest.TestCase):
    def test_ten_commands_and_ten_shims(self) -> None:
        self.assertEqual(len(COMMANDS), 10)
        self.assertEqual(len(SKILLS), 10)

    def test_every_command_allows_powershell_and_bash(self) -> None:
        for path in COMMANDS:
            match = re.search(r"^allowed-tools: (.*)$", read(path), re.M)
            self.assertIsNotNone(match, path.name)
            tools = [t.strip() for t in match.group(1).split(",")]
            self.assertIn("PowerShell", tools, path.name)
            self.assertIn("Bash", tools, path.name)

    def test_no_sh_wrapper_and_no_bash_only_syntax(self) -> None:
        for path in COMMANDS + SKILLS:
            text = read(path)
            self.assertNotIn('bin/gatekit"', text, path.name)
            self.assertNotIn("bin/gatekit ", text, path.name)
            self.assertNotIn("$(", text, "%s uses command substitution" % path.name)
            self.assertNotIn("| python3", text, path.name)
            self.assertNotRegex(text, r"python3\s*\n?\s*\"?\.claude/gatekit", path.name)
            self.assertNotIn("head -40", text, path.name)

    def test_every_invocation_uses_the_uv_form_with_a_real_subcommand(self) -> None:
        seen = 0
        for path in COMMANDS:
            for line in read(path).splitlines():
                if "bin/gatekit.py" not in line:
                    continue
                for match in re.finditer(re.escape(CLI) + r"(?: (\S+))?", line):
                    seen += 1
                    sub = (match.group(1) or "").strip("`")
                    self.assertIn(sub, cli.SUBCOMMANDS, "%s: %r" % (path.name, line))
                # every mention of the launcher must be the full uv form
                self.assertEqual(line.count("bin/gatekit.py"), line.count(CLI), "%s: %r" % (path.name, line))
        self.assertGreater(seen, 20)

    def test_lang_never_receives_arguments_through_a_shell_word(self) -> None:
        for path in COMMANDS:
            for line in read(path).splitlines():
                if " lang " in line and "bin/gatekit.py" in line:
                    self.assertIn("--file", line, "%s: %r" % (path.name, line))

    def test_mockup_merge_preset_call_is_fixed(self) -> None:
        text = read(PROJECT / ".claude" / "commands" / "gatekit" / "mockup.md")
        self.assertIn(CLI + " design merge-preset <name>", text)

    def test_build_reads_default_backend_with_workers_default(self) -> None:
        text = read(PROJECT / ".claude" / "commands" / "gatekit" / "build.md")
        self.assertIn(CLI + " workers default", text)

    def test_setup_runs_setup_script_and_asks_before_installing_uv(self) -> None:
        text = read(PROJECT / ".claude" / "commands" / "gatekit" / "setup.md")
        self.assertIn("powershell -NoProfile -ExecutionPolicy Bypass -File "
                      ".claude/gatekit/scripts/setup.ps1", text)
        self.assertIn("winget install --id=astral-sh.uv -e", text)
        self.assertIn("https://astral.sh/uv/install.ps1", text)
        self.assertRegex(text, r"only after\s+the user has agreed")

    def test_shims_stay_short_triggers(self) -> None:
        for path in SKILLS:
            self.assertLessEqual(len(read(path).splitlines()), 40, path.name)


if __name__ == "__main__":
    unittest.main()
