"""The skill docs and the reference docs they point at must run unchanged in
PowerShell and Git Bash: one uv-based invocation form, no bash-only syntax,
PowerShell allowed. Each pipeline is one skill folder under .claude/skills
(ADR-0020): SKILL.md is the entry point, references/ holds what a step reads
only when it needs it, assets/ holds templates and data."""
from __future__ import annotations

import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gatekit import cli, paths  # noqa: E402

PROJECT = pathlib.Path(__file__).resolve().parents[3]
KIT = PROJECT / ".claude" / "gatekit"
SKILLS = PROJECT / ".claude" / "skills"
SHARED = SKILLS / "gatekit-shared"
NAMES = ("build", "design", "discover", "doctor", "gate", "interview", "mockup",
         "setup", "tasks", "verify")
SKILL_DOCS = sorted(SKILLS.glob("gatekit-*/SKILL.md"))
#: Docs a skill tells the model to read; they carry commands and rules too.
REFERENCES = sorted(SKILLS.glob("gatekit-*/references/**/*.md"))
#: Folders the skills replaced. A checkout may still hold them as empty
#: directories (git does not track those), so the check is "no file inside".
REMOVED = (PROJECT / ".claude" / "commands", KIT / "policy", KIT / "spec-kit")
PREAMBLE = ".claude/skills/gatekit-shared/references/preamble.md"
CLI = paths.cli_invocation()
#: The same invocation written as a JSON argv list (a task gate runs without a shell).
CLI_ARGV = ", ".join('"%s"' % word for word in CLI.split())
STEP0 = re.compile(r"^## Step 0 [^\n]*\n(.*?)(?=^## )", re.M | re.S)
#: A file or a folder under .claude/skills, as written in a doc.
SKILL_PATH = re.compile(r"\.claude/skills/[\w./<>*-]*?(?:\.(?:md|json|ps1|py)\b|/(?=[`\s]))")


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def skill(name: str) -> pathlib.Path:
    return SKILLS / ("gatekit-" + name)


def rel(path: pathlib.Path) -> str:
    return path.relative_to(PROJECT).as_posix()


def one_line(text: str) -> str:
    return " ".join(text.split())


class TestSkillLayout(unittest.TestCase):
    def test_ten_skills_and_one_shared_folder(self) -> None:
        self.assertEqual([p.parent.name for p in SKILL_DOCS],
                         ["gatekit-" + name for name in NAMES])
        # gatekit-shared is not a skill: no SKILL.md, so it is never listed.
        self.assertTrue((SHARED / "references").is_dir())
        self.assertTrue((SHARED / "assets" / "heading-map.json").is_file())
        self.assertFalse((SHARED / "SKILL.md").exists())
        folders = sorted(p.name for p in SKILLS.iterdir() if p.is_dir())
        self.assertEqual(folders, sorted(["gatekit-" + n for n in NAMES] + ["gatekit-shared"]))

    def test_the_replaced_folders_hold_no_files(self) -> None:
        for folder in REMOVED:
            left = [rel(p) for p in folder.rglob("*") if p.is_file()] if folder.exists() else []
            self.assertEqual(left, [], "%s is replaced by .claude/skills" % rel(folder))

    def test_a_skill_folder_holds_only_the_known_parts(self) -> None:
        for folder in sorted(p for p in SKILLS.iterdir() if p.is_dir()):
            for child in folder.iterdir():
                self.assertIn(child.name, ("SKILL.md", "references", "assets", "scripts"),
                              rel(child))

    def test_every_skill_md_stays_under_500_lines(self) -> None:
        for path in SKILL_DOCS:
            self.assertLess(len(read(path).splitlines()), 500, rel(path))


class TestFrontmatter(unittest.TestCase):
    def test_name_is_the_folder_name(self) -> None:
        for path in SKILL_DOCS:
            text = read(path)
            self.assertTrue(text.startswith("---\n"), rel(path))
            match = re.search(r"^name: (.*)$", text, re.M)
            self.assertIsNotNone(match, rel(path))
            self.assertEqual(match.group(1), path.parent.name, rel(path))
            self.assertIn("\n# /%s\n" % path.parent.name, text, rel(path))

    def test_every_description_carries_triggers_and_a_boundary(self) -> None:
        for path in SKILL_DOCS:
            match = re.search(r"^description: (.*)$", read(path), re.M)
            self.assertIsNotNone(match, rel(path))
            text = match.group(1)
            self.assertLessEqual(len(text), 1024, rel(path))
            self.assertNotRegex(text, r"[<>]", rel(path))
            self.assertNotIn(": ", text, "%s: a colon-space breaks the YAML line" % rel(path))
            self.assertIn("Korean triggers", text, rel(path))
            self.assertRegex(text, r"[가-힣]", rel(path))
            self.assertIn("English triggers", text, rel(path))
            self.assertIn("NOT ", text, rel(path))
            # a neighbour is named the way it is typed, and it exists
            for other in re.findall(r"/gatekit-([a-z]+)", text):
                self.assertIn(other, NAMES, rel(path))

    def test_every_skill_allows_powershell_and_bash(self) -> None:
        for path in SKILL_DOCS:
            match = re.search(r"^allowed-tools: (.*)$", read(path), re.M)
            self.assertIsNotNone(match, rel(path))
            tools = [t.strip() for t in match.group(1).split(",")]
            self.assertIn("PowerShell", tools, rel(path))
            self.assertIn("Bash", tools, rel(path))


class TestPointers(unittest.TestCase):
    def test_every_step_zero_points_at_the_preamble(self) -> None:
        self.assertTrue((PROJECT / PREAMBLE).is_file())
        for path in SKILL_DOCS:
            match = STEP0.search(read(path))
            self.assertIsNotNone(match, rel(path))
            step = match.group(1)
            self.assertIn(PREAMBLE, one_line(step), rel(path))
            self.assertRegex(step, r"\*\*from the (spec|input)\*\*", rel(path))
            self.assertNotIn("bin/gatekit.py", step, "%s repeats the preamble" % rel(path))

    def test_every_skill_path_a_doc_names_exists(self) -> None:
        seen = 0
        for path in SKILL_DOCS + REFERENCES:
            for ref in SKILL_PATH.findall(read(path)):
                langs = ("ko", "en") if "<output_lang>" in ref else ("",)
                for lang in langs:
                    target = ref.replace("<output_lang>", lang)
                    if "<" in target or "*" in target:
                        continue  # a pattern such as gatekit-<name>/ or *.json
                    seen += 1
                    found = PROJECT / target
                    ok = found.is_dir() if target.endswith("/") else found.is_file()
                    self.assertTrue(ok, "%s names %s" % (rel(path), target))
        self.assertGreater(seen, 60)

    def test_no_doc_points_at_a_replaced_folder_or_the_colon_name(self) -> None:
        for path in sorted(p for p in SKILLS.rglob("*") if p.is_file()):
            text = read(path)
            self.assertNotIn("/gatekit:", text, "%s: the name is /gatekit-<name>" % rel(path))
            self.assertNotIn(".claude/commands", text, rel(path))
            self.assertNotIn("spec-kit", text, rel(path))
            self.assertNotRegex(text, r"(?<![\w-])policy/", rel(path))
            self.assertNotRegex(text, r"(?<![\w-])templates/", rel(path))

    def test_no_doc_tells_the_model_to_read_docs(self) -> None:
        # docs/ is written for people. A skill may tell the user that a guide
        # exists, but it never names a docs/ path as something to open.
        for path in SKILL_DOCS + REFERENCES:
            self.assertNotRegex(read(path), r"`docs/", rel(path))

    def test_every_skill_reference_says_when_to_read_it(self) -> None:
        for path in REFERENCES:
            if path.is_relative_to(SHARED):
                continue  # shared rules are read at Step 0, through the preamble
            head = one_line("\n".join(read(path).splitlines()[:8]))
            self.assertRegex(head, r"\bRead (this|by)\b", rel(path))
            self.assertIn("/" + path.parents[1].name, head, rel(path))


class TestShellNeutral(unittest.TestCase):
    def test_no_sh_wrapper_and_no_bash_only_syntax(self) -> None:
        for path in SKILL_DOCS + REFERENCES:
            text = read(path)
            self.assertNotIn('bin/gatekit"', text, rel(path))
            self.assertNotIn("bin/gatekit ", text, rel(path))
            self.assertNotIn("$(", text, "%s uses command substitution" % rel(path))
            self.assertNotIn("| python3", text, rel(path))
            self.assertNotRegex(text, r"python3\s*\n?\s*\"?\.claude/gatekit", rel(path))
            self.assertNotIn("head -40", text, rel(path))

    def test_every_invocation_uses_the_uv_form_with_a_real_subcommand(self) -> None:
        seen = 0
        for path in SKILL_DOCS + REFERENCES:
            for line in read(path).splitlines():
                if "bin/gatekit.py" not in line:
                    continue
                for match in re.finditer(re.escape(CLI) + r"(?: (\S+))?", line):
                    seen += 1
                    sub = (match.group(1) or "").strip("`")
                    self.assertIn(sub, cli.SUBCOMMANDS, "%s: %r" % (rel(path), line))
                # every mention of the launcher must be the full uv form
                self.assertEqual(line.count("bin/gatekit.py"), line.count(CLI) + line.count(CLI_ARGV),
                                 "%s: %r" % (rel(path), line))
        self.assertGreater(seen, 20)

    def test_lang_never_receives_arguments_through_a_shell_word(self) -> None:
        for path in SKILL_DOCS + REFERENCES:
            for line in read(path).splitlines():
                if " lang " in line and "bin/gatekit.py" in line:
                    self.assertIn("--file", line, "%s: %r" % (rel(path), line))


class TestSkillBodies(unittest.TestCase):
    def test_mockup_merge_preset_call_is_fixed(self) -> None:
        text = read(skill("mockup") / "SKILL.md")
        self.assertIn(CLI + " design merge-preset <name>", text)
        self.assertIn(".claude/skills/gatekit-shared/assets/presets/design/", text)

    def test_build_reads_default_backend_with_workers_default(self) -> None:
        text = read(skill("build") / "SKILL.md")
        self.assertIn(CLI + " workers default", text)

    def test_rare_paths_live_in_reference_docs(self) -> None:
        build = read(skill("build") / "SKILL.md")
        self.assertIn(".claude/skills/gatekit-build/references/build-failures.md", build)
        self.assertIn("jobs recheck", read(skill("build") / "references" / "build-failures.md"))
        gate = read(skill("gate") / "SKILL.md")
        self.assertIn(".claude/skills/gatekit-gate/references/gate-criteria.md", gate)
        self.assertIn("gatekit-criterion", read(skill("gate") / "references" / "gate-criteria.md"))

    def test_templates_sit_with_the_skill_that_writes_them(self) -> None:
        owners = {"discover": ["00-discovery.md"], "interview": ["01-prd.md", "03-architecture.md"],
                  "mockup": ["02-screens.md"], "design": ["02-design.md"],
                  "tasks": ["04-tasks.md"], "gate": ["05-gate.md"],
                  "build": ["PROGRESS.md", "RECOVERY.md"]}
        for name, files in owners.items():
            for lang in ("ko", "en"):
                found = sorted(p.name for p in (skill(name) / "assets" / lang).glob("*.md"))
                self.assertEqual(found, files, "gatekit-%s/assets/%s" % (name, lang))


class TestSetupSkill(unittest.TestCase):
    def setUp(self) -> None:
        self.body = read(skill("setup") / "SKILL.md")
        self.refs = skill("setup") / "references"

    def test_setup_runs_the_setup_script_and_asks_before_installing(self) -> None:
        self.assertIn("powershell -NoProfile -ExecutionPolicy Bypass -File "
                      ".claude/gatekit/scripts/setup.ps1 -Json -Lang <output_lang>", self.body)
        self.assertRegex(self.body, r"only after\s+the user has agreed")
        # the safety rules stay in the body, not in a file read only sometimes
        flat = one_line(self.body)
        self.assertIn("A reinstall and a retry are separate permissions", flat)
        self.assertIn("Never enable a bypass flag", flat)

    def test_setup_names_its_three_references_and_when_to_read_them(self) -> None:
        self.assertEqual(sorted(p.name for p in self.refs.glob("*.md")),
                         ["install-programs.md", "rare-paths.md", "settings.md"])
        for name, when in (("install-programs.md", "Step 3"),
                           ("settings.md", "S12-settings"),
                           ("rare-paths.md", "P-failures")):
            self.assertIn(".claude/skills/gatekit-setup/references/" + name, self.body)
            self.assertIn(when, read(self.refs / name).split("\n\n")[1], name)

    def test_uv_manual_install_commands_are_in_install_programs(self) -> None:
        text = read(self.refs / "install-programs.md")
        self.assertIn("winget install --id=astral-sh.uv -e", text)
        self.assertIn("https://astral.sh/uv/install.ps1", text)
        self.assertNotIn("astral.sh/uv/install.ps1", self.body)

    def test_install_programs_covers_every_program(self) -> None:
        text = read(self.refs / "install-programs.md")
        for name in ("winget", "pwsh", "uv", "claude", "venv", "git"):
            self.assertRegex(text, r"(?m)^\| `%s` \|" % name)
        self.assertIn("`-Install winget`", text)
        self.assertIn("-Install winget,pwsh", text)
        self.assertRegex(text, r"(?m)^\| `winget` \|[^|]*\| recommended \|")
        self.assertRegex(text, r"(?m)^\| `pwsh` \|[^|]*\| required \|")

    def test_settings_reference_carries_both_required_values(self) -> None:
        text = read(self.refs / "settings.md")
        self.assertIn("CLAUDE_CODE_USE_POWERSHELL_TOOL", text)
        self.assertIn('"defaultShell": "powershell"', text)
        self.assertIn("only the missing key", one_line(text))

    def test_rare_paths_reference_covers_the_rare_switches(self) -> None:
        text = read(self.refs / "rare-paths.md")
        for switch in ("-Reinstall", "-RetryFailed", "-Status"):
            self.assertIn(switch, text)
        self.assertIn("a separate yes", text)

    def test_reopen_wording_does_not_assume_one_environment(self) -> None:
        phrase = ("close Claude Code completely (the desktop app, the VS Code window, "
                  "or the terminal it runs in) and open it again")
        self.assertIn(phrase, one_line(self.body))
        self.assertIn(phrase, one_line(read(self.refs / "settings.md")))


if __name__ == "__main__":
    unittest.main()
