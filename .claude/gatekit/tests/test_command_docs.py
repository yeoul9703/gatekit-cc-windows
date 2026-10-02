"""The command docs and the reference docs they point at must run unchanged in
PowerShell and Git Bash: one uv-based invocation form, no bash-only syntax,
PowerShell allowed. The commands are the only entry points (ADR-0019)."""
from __future__ import annotations

import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gatekit import cli, paths  # noqa: E402

PROJECT = pathlib.Path(__file__).resolve().parents[3]
COMMANDS = sorted((PROJECT / ".claude" / "commands" / "gatekit").glob("*.md"))
KIT = PROJECT / ".claude" / "gatekit"
#: Docs a command tells the model to read; they carry commands and rules too.
REFERENCES = sorted((KIT / "policy").glob("*.md")) + sorted((KIT / "spec-kit").glob("*.md"))
CLI = paths.cli_invocation()
#: The same invocation written as a JSON argv list (a task gate runs without a shell).
CLI_ARGV = ", ".join('"%s"' % word for word in CLI.split())
STEP0 = re.compile(r"^## Step 0 [^\n]*\n(.*?)(?=^## )", re.M | re.S)


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class TestCommandDocs(unittest.TestCase):
    def test_ten_commands_and_no_skill_shims(self) -> None:
        self.assertEqual(len(COMMANDS), 10)
        # /gatekit:<name> exists only as a command file; a second entry under
        # .claude/skills would list every pipeline twice (ADR-0019).
        self.assertEqual(sorted((PROJECT / ".claude" / "skills").glob("gatekit-*")), [])

    def test_every_description_carries_triggers_and_a_boundary(self) -> None:
        for path in COMMANDS:
            match = re.search(r"^description: (.*)$", read(path), re.M)
            self.assertIsNotNone(match, path.name)
            text = match.group(1)
            self.assertLessEqual(len(text), 1024, path.name)
            self.assertNotRegex(text, r"[<>]", path.name)
            self.assertNotIn(": ", text, "%s: a colon-space breaks the YAML line" % path.name)
            self.assertIn("Korean triggers", text, path.name)
            self.assertRegex(text, r"[가-힣]", path.name)
            self.assertIn("English triggers", text, path.name)
            self.assertIn("NOT ", text, path.name)

    def test_every_step_zero_points_at_the_preamble(self) -> None:
        self.assertTrue((KIT / "policy" / "preamble.md").is_file())
        for path in COMMANDS:
            match = STEP0.search(read(path))
            self.assertIsNotNone(match, path.name)
            step = match.group(1)
            self.assertIn(".claude/gatekit/policy/preamble.md", step, path.name)
            self.assertRegex(step, r"\*\*from the (spec|input)\*\*", path.name)
            self.assertNotIn("bin/gatekit.py", step, "%s repeats the preamble" % path.name)

    def test_every_reference_a_command_names_exists(self) -> None:
        for path in COMMANDS:
            for ref in re.findall(r"`(\.claude/gatekit/(?:policy|spec-kit)/[\w-]+\.(?:md|json))`", read(path)):
                self.assertTrue((PROJECT / ref).is_file(), "%s names %s" % (path.name, ref))

    def test_every_command_allows_powershell_and_bash(self) -> None:
        for path in COMMANDS:
            match = re.search(r"^allowed-tools: (.*)$", read(path), re.M)
            self.assertIsNotNone(match, path.name)
            tools = [t.strip() for t in match.group(1).split(",")]
            self.assertIn("PowerShell", tools, path.name)
            self.assertIn("Bash", tools, path.name)

    def test_no_sh_wrapper_and_no_bash_only_syntax(self) -> None:
        for path in COMMANDS + REFERENCES:
            text = read(path)
            self.assertNotIn('bin/gatekit"', text, path.name)
            self.assertNotIn("bin/gatekit ", text, path.name)
            self.assertNotIn("$(", text, "%s uses command substitution" % path.name)
            self.assertNotIn("| python3", text, path.name)
            self.assertNotRegex(text, r"python3\s*\n?\s*\"?\.claude/gatekit", path.name)
            self.assertNotIn("head -40", text, path.name)

    def test_every_invocation_uses_the_uv_form_with_a_real_subcommand(self) -> None:
        seen = 0
        for path in COMMANDS + REFERENCES:
            for line in read(path).splitlines():
                if "bin/gatekit.py" not in line:
                    continue
                for match in re.finditer(re.escape(CLI) + r"(?: (\S+))?", line):
                    seen += 1
                    sub = (match.group(1) or "").strip("`")
                    self.assertIn(sub, cli.SUBCOMMANDS, "%s: %r" % (path.name, line))
                # every mention of the launcher must be the full uv form
                self.assertEqual(line.count("bin/gatekit.py"), line.count(CLI) + line.count(CLI_ARGV),
                                 "%s: %r" % (path.name, line))
        self.assertGreater(seen, 20)

    def test_lang_never_receives_arguments_through_a_shell_word(self) -> None:
        for path in COMMANDS + REFERENCES:
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

    def test_rare_paths_live_in_reference_docs(self) -> None:
        build = read(PROJECT / ".claude" / "commands" / "gatekit" / "build.md")
        self.assertIn(".claude/gatekit/spec-kit/build-failures.md", build)
        self.assertIn("jobs recheck", read(KIT / "spec-kit" / "build-failures.md"))
        gate = read(PROJECT / ".claude" / "commands" / "gatekit" / "gate.md")
        self.assertIn(".claude/gatekit/spec-kit/gate-criteria.md", gate)
        self.assertIn("gatekit-criterion", read(KIT / "spec-kit" / "gate-criteria.md"))


if __name__ == "__main__":
    unittest.main()
