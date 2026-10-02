"""The skill docs and the reference docs they point at must run unchanged in
PowerShell and Git Bash: one uv-based invocation form, no bash-only syntax,
PowerShell allowed. Each pipeline is one skill folder under .claude/skills
(ADR-0020): SKILL.md is the entry point, references/ holds what a step reads
only when it needs it, assets/ holds templates and data."""
from __future__ import annotations

import json
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
            for target in SKILL_PATH.findall(read(path)):
                # the templates are one Korean set: no path is built from a language
                self.assertNotIn("<output_lang>", target, rel(path))
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

    def test_no_skill_document_calls_a_removed_command_or_names_a_removed_setting(self) -> None:
        # A job starts no process: there is nothing to wait for, hand a task back to or
        # review with, and no setting that chooses a program.
        from gatekit import jobs
        seen = 0
        for path in SKILL_DOCS + REFERENCES:
            text = read(path)
            called = (re.findall(r"`jobs ([a-z]+)", text)
                      + re.findall(re.escape(CLI) + r" jobs ([a-z]+)", text))
            for sub in called:
                seen += 1
                self.assertIn(sub, jobs.COMMAND_NAMES, "%s: jobs %s" % (rel(path), sub))
            for gone in ("build.execution", "verify.evaluator", "worker.backends",
                         "--backend", "--parallel", "`execution`"):
                self.assertNotIn(gone, text, "%s: %s" % (rel(path), gone))
        self.assertGreater(seen, 20)

    def test_build_and_gate_say_what_is_never_edited_by_hand(self) -> None:
        # The approval record, the derived contract, the gate code and the hook registration
        # are what holds the user's approval. Both skills say it in the same words, and name
        # the two ways forward when a criterion does not pass.
        never = ("Never edit these by hand: `.gatekit/approvals.json`, `.gatekit/contract.json`, "
                 "the gate code and scripts under `.claude/`, and the `hooks` in "
                 "`.claude/settings.json`.")
        ways = ("When a criterion does not pass there are two ways forward: fix the code, or, "
                "if the criterion is wrong, return to `/gatekit-gate` and have the user approve "
                "it again.")
        for name in ("build", "gate"):
            flat = one_line(read(skill(name) / "SKILL.md"))
            self.assertIn(never, flat, "gatekit-" + name)
            self.assertIn(ways, flat, "gatekit-" + name)
            self.assertIn("The Stop gate reads the approval and `spec/05-gate.md` itself", flat,
                          "gatekit-" + name)
        # build says it where failures are routed, gate where the approval is recorded
        build = read(skill("build") / "SKILL.md")
        self.assertIn("Never edit these by hand", build.split("\n## Step 6 — route failures\n")[1]
                      .split("\n## ")[0])
        gate = read(skill("gate") / "SKILL.md")
        self.assertIn("Never edit these by hand", gate.split("\n## Step 6 — approve\n")[1]
                      .split("\n## ")[0])

    def test_build_hands_a_round_of_two_out_and_builds_a_single_task_itself(self) -> None:
        text = read(skill("build") / "SKILL.md")
        flat = one_line(text)
        allowed = re.search(r"^allowed-tools: (.*)$", text, re.M)
        assert allowed is not None
        self.assertIn("Agent", [t.strip() for t in allowed.group(1).split(",")])
        self.assertIn("**One task in the round — you build it.**", flat)
        self.assertIn("**Two or more tasks in the round — hand every one out.**", flat)
        self.assertIn("**passed on exactly as printed**", flat)
        # the result of a round is the record, not what a subagent answered
        self.assertIn(CLI + " jobs results --compact", text)
        self.assertIn("Do not read a subagent's transcript", flat)
        # a returned task is fixed here, and a gate edit is rechecked: neither is handed out again
        failures = one_line(read(skill("build") / "references" / "build-failures.md"))
        self.assertIn("**Do not hand the same task out again.**", failures)
        self.assertIn("never hand the task out again for one", failures)
        # the text the skill shows is the text `jobs start` prints
        from gatekit import jobs
        printed = jobs.handoff_text("<job id>", {"id": "<task id>",
                                                 "write_scope": ["<the task's write scope>"]})
        self.assertIn("hand off <task id> (round <n>):\n" + printed + "\n", text)

    def test_tasks_names_the_read_field_the_brief_is_built_from(self) -> None:
        flat = one_line(read(skill("tasks") / "SKILL.md"))
        self.assertIn("`read`", flat)
        self.assertIn("relative to the project root", flat)
        self.assertIn("never with an `@`", flat)
        template = read(skill("tasks") / "assets" / "04-tasks.md")
        self.assertIn('"read": [', template)
        self.assertRegex(template, r"(?m)^\| `read` \|")

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
            found = sorted(p.name for p in (skill(name) / "assets").glob("*.md"))
            self.assertEqual(found, files, "gatekit-%s/assets" % name)
        # one Korean set: no skill keeps a folder per language
        for child in sorted(SKILLS.glob("gatekit-*/assets/*")):
            self.assertNotIn(child.name, ("ko", "en"), rel(child))


class TestHandoff(unittest.TestCase):
    """Every skill ends the same way: it points at the shared handoff rule and
    adds only its own next skill. Setup is edited apart and names its next
    command itself, so it is in the table but not in the pointer check."""

    HANDOFF = ".claude/skills/gatekit-shared/references/handoff.md"

    def setUp(self) -> None:
        self.rule = read(PROJECT / self.HANDOFF)

    def table_rows(self) -> dict:
        rows = {}
        for line in self.rule.splitlines():
            match = re.match(r"\| `/gatekit-([a-z]+)` \|(.*)\|\s*$", line)
            if match:
                rows[match.group(1)] = match.group(2)
        return rows

    def test_the_last_step_of_every_skill_points_at_the_handoff_rule(self) -> None:
        for name in NAMES:
            if name == "setup":
                continue
            text = read(skill(name) / "SKILL.md")
            title, _, body = text.rpartition("\n## ")[2].partition("\n")
            self.assertRegex(title, r"^Step [\d.]+ — hand off$", "gatekit-" + name)
            self.assertIn(self.HANDOFF, one_line(body), "gatekit-" + name)
            # the rule is named once, at the end, and not copied into the skill
            self.assertEqual(text.count(self.HANDOFF), 1, "gatekit-" + name)
            self.assertNotIn("ask what happens next", text, "gatekit-" + name)

    def test_the_last_step_says_how_the_question_is_asked(self) -> None:
        # discover never opens the question window; the picker is never
        # auto-approved through allowed-tools (questioning.md).
        for name in NAMES:
            if name == "setup":
                continue
            text = read(skill(name) / "SKILL.md")
            last = one_line(text.rpartition("\n## ")[2])
            self.assertRegex(last, r"plain chat|`AskUserQuestion`", "gatekit-" + name)
            allowed = re.search(r"^allowed-tools: (.*)$", text, re.M).group(1)
            self.assertNotIn("AskUserQuestion", allowed, "gatekit-" + name)
        self.assertIn("plain chat", read(skill("discover") / "SKILL.md").rpartition("\n## ")[2])

    def test_the_handoff_table_has_a_row_for_every_skill(self) -> None:
        rows = self.table_rows()
        self.assertEqual(sorted(rows), sorted(NAMES))
        for name, rest in rows.items():
            for other in re.findall(r"/gatekit-([a-z]+)", rest):
                self.assertIn(other, NAMES, "row %s names /gatekit-%s" % (name, other))

    def test_the_handoff_table_follows_the_required_path(self) -> None:
        rows = self.table_rows()
        usual = {name: rest.split("|")[0] for name, rest in rows.items()}
        for name, following in (("discover", "interview"), ("interview", "mockup"),
                                ("mockup", "tasks"), ("tasks", "gate"),
                                ("gate", "build"), ("build", "verify")):
            self.assertIn("`/gatekit-%s`" % following, usual[name], name)
        self.assertNotIn("/gatekit-", usual["verify"])
        # a project with screens cannot skip mockup; only [non-ui] goes around it
        self.assertIn("[non-ui]", rows["interview"])
        self.assertIn("Prototype confirmed", rows["mockup"])

    def test_the_handoff_rule_keeps_the_safety_rules(self) -> None:
        flat = one_line(self.rule)
        self.assertIn("invoking the next skill", flat)
        self.assertIn("never approves for the user", flat)
        self.assertIn("never fixes what it finds", flat)
        self.assertRegex(flat, r"never hands off while a task is `failed`, `stopped` or "
                               r"still `queued`")
        self.assertIn("do not offer to go on", flat)
        # and each of the three skills still says it in its own body
        self.assertIn("Do not approve on their behalf", one_line(read(skill("gate") / "SKILL.md")))
        self.assertIn("do not hand off", one_line(read(skill("gate") / "SKILL.md")))
        self.assertIn("do not hand off", one_line(read(skill("build") / "SKILL.md")))
        self.assertIn("Do not fix the code here", one_line(read(skill("verify") / "SKILL.md")))

    def test_build_tells_the_user_before_the_job_starts(self) -> None:
        body = read(skill("build") / "SKILL.md")
        notice = ".claude/skills/gatekit-build/references/build-notice.md"
        self.assertIn(notice, one_line(body))
        self.assertLess(body.index("build-notice.md"), body.index(CLI + " jobs start"))
        text = read(PROJECT / notice)
        self.assertIn(CLI + " jobs shape", text)
        self.assertIn(CLI + " jobs status", text)
        self.assertIn(CLI + " jobs start --tasks", text)
        for word in ("`max_retries`", "jobs complete", "jobs stop"):
            self.assertIn(word, one_line(text), word)
        # nothing here measures time or cost, so the notice gives no figure for them
        self.assertNotRegex(text, r"\d+\s*(minutes?|hours?|tokens|dollars|%)")

    def test_usage_names_every_skill_and_the_order(self) -> None:
        usage = read(PROJECT / "docs" / "USAGE.md")
        for name in NAMES:
            self.assertIn("`/gatekit-%s`" % name, usage, name)
        top = usage[:usage.index("\n## 1.")]
        for name in NAMES:
            self.assertIn("/gatekit-%s" % name, top, "the first screen misses " + name)
        order = [top.index("/gatekit-" + n) for n in ("setup", "interview", "tasks",
                                                       "gate", "build", "verify")]
        self.assertEqual(order, sorted(order))
        self.assertIn("`/doctor`", top)


class TestSetupSkill(unittest.TestCase):
    def setUp(self) -> None:
        self.body = read(skill("setup") / "SKILL.md")
        self.refs = skill("setup") / "references"
        # The skill as a whole: SKILL.md plus the reference files its steps read.
        self.text = "\n".join([self.body] + [read(p) for p in sorted(self.refs.glob("*.md"))])

    def test_setup_runs_the_setup_script_and_asks_before_installing(self) -> None:
        self.assertIn("powershell -NoProfile -ExecutionPolicy Bypass -File "
                      ".claude/gatekit/scripts/setup.ps1 -Json -Lang <output_lang>", self.body)
        self.assertRegex(self.body, r"only after\s+the user has agreed")
        # every call of the script, in the body and in the references, passes -Lang
        calls = [line for line in self.text.splitlines() if "scripts/setup.ps1" in line and "-File" in line]
        self.assertGreaterEqual(len(calls), 2)
        for line in calls:
            self.assertIn("-Lang", line)
        self.assertIn("Always pass `-Lang <output_lang>`", self.text)
        # the safety rules stay in the body, not in a file read only sometimes
        flat = one_line(self.body)
        self.assertIn("A reinstall and a retry are separate permissions", flat)
        self.assertIn("Never enable a bypass flag", flat)

    def test_setup_asks_with_one_question_and_does_not_auto_approve_it(self) -> None:
        # TestHandoff leaves setup out, so the allowed-tools rule is checked here.
        front = self.body.split("---")[1]
        allowed = [line for line in front.splitlines() if line.startswith("allowed-tools:")]
        self.assertEqual(len(allowed), 1)
        self.assertNotIn("AskUserQuestion", allowed[0])
        self.assertIn("AskUserQuestion", self.body.split("---", 2)[2])
        self.assertIn("-Install", self.body)

    def test_candidates_include_warn_items_and_update_flow(self) -> None:
        # S27: the setup skill covers warn candidates, -Update, -Install venv and -Lang.
        self.assertIn("`fail` **or `warn`**", self.text)
        self.assertIn("-Update uv", self.text)
        self.assertIn("-Update pwsh", self.text)
        self.assertIn("-Update claude", self.text)

    def test_venv_question_mentions_the_download_size(self) -> None:
        self.assertIn("-Install venv", self.text)
        self.assertIn("tens of MB", self.text)
        self.assertIn("deleted and rebuilt", self.text)

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
        self.assertRegex(text, r"(?m)^\| `uv` \|[^|]*\| required \|")
        self.assertRegex(text, r"(?m)^\| `git` \| `-Install git` only \| recommended \|")

    def test_git_is_a_recommended_candidate_installed_in_the_user_scope_first(self) -> None:
        text = read(self.refs / "install-programs.md")
        flat = one_line(text)
        packages = json.loads(read(KIT / "scripts" / "packages.json"))["packages"]
        git = next(p for p in packages if p["key"] == "git")
        self.assertEqual(git["level"], "권장")
        # the same command as the script and the people's reference
        self.assertIn("`winget install --id %s -e --source winget --scope user`" % git["winget_id"], flat)
        self.assertIn("-Install winget,git", flat)
        for word in ("`S7`", "`S10-git`", "`S16-git`"):
            self.assertIn(word, flat, word)
        # the model warns about the administrator prompt itself, before the install runs
        self.assertIn("**Say this in the chat before you run `-Install git`**", flat)
        self.assertIn("it can open behind other windows", flat)
        self.assertIn("관리자 확인 창이 뜰 수 있습니다", flat)
        self.assertIn("no elevation tool (gsudo,", flat)
        for stale in ("the script never installs it", "prints a command only"):
            self.assertNotIn(stale, flat)
        body = one_line(self.body)
        self.assertIn("**Git (`S7`) is a candidate**", body)
        self.assertIn("tell the user **before** you run the command that a Windows administrator prompt may appear", body)

    def test_the_claude_command_is_never_needed_and_stays_out_of_install_all(self) -> None:
        # gatekit starts no claude process: S6 only shows the Claude Code version.
        text = read(self.refs / "install-programs.md")
        row = re.search(r"(?m)^\| `claude` \|[^|]*\| recommended \|([^|]*)\|", text)
        assert row is not None
        self.assertIn("gatekit never starts it", row.group(1))
        self.assertIn('never inside "install all"', one_line(text))
        self.assertIn("do not offer an install just to read a version", one_line(text))
        body = one_line(self.body)
        self.assertIn("gatekit needs three programs: Claude Code, **uv** and **PowerShell 7**", body)
        self.assertIn("the desktop app, the VS Code extension or the terminal", body)
        self.assertIn("**The Claude Code version (`S6`) is never a candidate.**", body)
        self.assertIn("never offer to install the CLI just to read a version", body)
        self.assertIn("the app should be kept up to date", body)
        for stale in ("does not provide it", "A missing `claude` CLI is fixed"):
            self.assertNotIn(stale, one_line(self.text))
        # the example install call does not install what gatekit never starts
        calls = [line for line in self.body.splitlines() if "setup.ps1 -Install" in line]
        self.assertEqual(len(calls), 1)
        self.assertNotIn("claude", calls[0].split("-Install", 1)[1])
        # setup makes the state folder and writes no settings file; doctor has no axis for a program
        self.assertNotIn("config.json", self.text)
        doctor = one_line(read(skill("doctor") / "SKILL.md"))
        self.assertIn("The seven axes are", doctor)
        self.assertNotIn("`claude`", doctor)

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
        # closing the window of the desktop app is not enough: the exit code 3 step says where to quit it
        step = one_line(self.body[self.body.index("- `3` —"):self.body.index("- `4` —")])
        self.assertIn(phrase, step)
        self.assertIn("quit from the Claude icon in the notification area (bottom right of the taskbar)", step)
        self.assertIn("작업 표시줄 오른쪽 아래(트레이)의 Claude 아이콘에서 종료하세요", step)


if __name__ == "__main__":
    unittest.main()
