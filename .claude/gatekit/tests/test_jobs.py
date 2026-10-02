"""Tests for gatekit.jobs — job dirs, the plan, gate verdicts, the retry budget.

A job starts no process: `start` writes the task directories and hands back the
plan, and `complete_task` runs the gates. The gates here are small python
scripts, so no agent CLI and no network is needed.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import jobs, verdict

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "jobs"
GATE_EXISTS = FIXTURES / "gate_file_exists.py"


def task_fence(task: dict) -> str:
    return "```gatekit-task\n%s\n```\n" % json.dumps(task)


class JobTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        (self.root / "src").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------

    def write_config(self) -> None:
        """The one build setting a job reads: the retry budget."""
        cfg = {"build": {"max_retries": 2}}
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def write_note(self, body: str = "done") -> None:
        """Do the work of `simple_task()` by hand, as the session would."""
        (self.root / "src" / "note.txt").write_text(body, encoding="utf-8")

    def write_tasks(self, *tasks) -> None:
        body = "# Tasks\n\n" + "\n".join(task_fence(t) for t in tasks)
        (self.root / "spec" / "04-tasks.md").write_text(body, encoding="utf-8")

    def simple_task(self, task_id="write-note", target="src/note.txt", **extra) -> dict:
        task = {
            "id": task_id,
            "title": "Write a note",
            "write_scope": [target],
            "instruction": "Create %s." % target,
            "gates": [{"name": "file-exists",
                       "argv": [sys.executable, str(GATE_EXISTS), target]}],
            "depends_on": [],
            "round": 1,
        }
        task.update(extra)
        return task

    def task_dir(self, job_id, task_id) -> pathlib.Path:
        return self.root / ".gatekit" / "jobs" / job_id / "tasks" / task_id


# ------------------------------------------------------------------- basics


class TestJobId(unittest.TestCase):
    def test_job_id_is_timestamp_plus_four_hex(self) -> None:
        job_id = jobs.new_job_id()
        stamp, suffix = job_id.rsplit("-", 1)
        self.assertEqual(len(suffix), 4)
        int(suffix, 16)  # must parse as hex
        self.assertTrue(stamp.endswith("Z"))
        self.assertNotEqual(jobs.new_job_id(), job_id)


class TestAtomicWrite(JobTestCase):
    def test_write_json_leaves_no_temp_files(self) -> None:
        target = self.root / "sub" / "x.json"
        jobs.write_json(target, {"a": 1})
        self.assertEqual(json.loads(target.read_text()), {"a": 1})
        # Nothing but the target may be left behind, whatever the temp files are called.
        self.assertEqual([p.name for p in target.parent.iterdir()], ["x.json"])

    def test_write_json_replaces_existing_content(self) -> None:
        target = self.root / "x.json"
        jobs.write_json(target, {"a": 1})
        jobs.write_json(target, {"b": 2})
        self.assertEqual(json.loads(target.read_text()), {"b": 2})


class TestPrompt(JobTestCase):
    def test_prompt_carries_instruction_scope_gates_and_no_success_claim(self) -> None:
        task = self.simple_task()
        prompt = jobs.build_prompt(task, "job-1")
        self.assertIn("Create src/note.txt.", prompt)
        self.assertIn("src/note.txt", prompt)
        self.assertIn("file-exists", prompt)
        self.assertIn("Do not claim success", prompt)
        self.assertIn("gates decide", prompt)


class TestOrdering(unittest.TestCase):
    def test_depends_on_lands_in_a_later_wave(self) -> None:
        tasks = [
            {"id": "b", "depends_on": ["a"], "round": 1},
            {"id": "a", "depends_on": [], "round": 1},
        ]
        waves = jobs.order_tasks(tasks)
        self.assertEqual([t["id"] for t in waves[0]], ["a"])
        self.assertEqual([t["id"] for t in waves[1]], ["b"])

    def test_rounds_are_honoured_before_dependencies(self) -> None:
        tasks = [
            {"id": "late", "depends_on": [], "round": 2},
            {"id": "early", "depends_on": [], "round": 1},
        ]
        waves = jobs.order_tasks(tasks)
        self.assertEqual([t["id"] for t in waves[0]], ["early"])
        self.assertEqual([t["id"] for t in waves[1]], ["late"])

    def test_dependency_cycle_still_schedules_every_task(self) -> None:
        tasks = [
            {"id": "a", "depends_on": ["b"], "round": 1},
            {"id": "b", "depends_on": ["a"], "round": 1},
        ]
        scheduled = [t["id"] for wave in jobs.order_tasks(tasks) for t in wave]
        self.assertEqual(sorted(scheduled), ["a", "b"])


# ------------------------------------------------------------------- running


class TestStart(JobTestCase):
    def test_dry_run_creates_the_task_dirs_and_leaves_tasks_queued(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        tdir = self.task_dir(job["job_id"], "write-note")
        self.assertTrue((tdir / "task.json").is_file())
        self.assertTrue((tdir / "prompt.md").is_file())
        self.assertFalse((self.root / "src" / "note.txt").exists())
        status = json.loads((tdir / "status.json").read_text())
        self.assertEqual(status["state"], "queued")

    def test_unknown_task_id_is_rejected(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        with self.assertRaises(ValueError):
            jobs.start(self.root, task_ids=["ghost"])

    def test_no_tasks_is_rejected(self) -> None:
        self.write_config()
        (self.root / "spec" / "04-tasks.md").write_text("# empty\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            jobs.start(self.root)

    def test_settings_an_older_kit_wrote_start_nothing(self) -> None:
        # worker.backends, build.execution and verify.evaluator are read by nothing: the
        # backend named here does not exist, and the job is prepared all the same.
        cfg = {"worker": {"default": "gone", "backends": {"gone": {
                   "argv": ["definitely-not-a-real-binary-xyz"], "enabled": True}}},
               "build": {"execution": "worker", "parallel": 3, "task_timeout_s": 1},
               "verify": {"evaluator": "gone"}}
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        self.assertEqual([row["id"] for row in job["plan"]], ["write-note"])
        tdir = self.task_dir(job["job_id"], "write-note")
        self.assertEqual(json.loads((tdir / "status.json").read_text())["state"], "queued")
        self.assertEqual(sorted(p.name for p in tdir.iterdir()),
                         ["preflight.json", "prompt.md", "status.json", "task.json"])
        saved = json.loads((self.root / ".gatekit" / "jobs" / job["job_id"] / "job.json").read_text())
        for gone in ("backend", "execution", "parallel", "task_timeout_s"):
            self.assertNotIn(gone, saved)


# ---------------------------------------------------------------- reporting


class TestStatusAndResults(JobTestCase):
    def test_status_reports_fail_when_a_task_failed(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        jobs.complete_task(self.root, "write-note", job_id=job["job_id"])  # nothing was written
        payload = jobs.status(self.root, job["job_id"])
        self.assertEqual(payload["verdict"], verdict.FAIL)
        self.assertTrue(payload["done"])

    def test_status_without_any_job_is_unverified(self) -> None:
        payload = jobs.status(self.root)
        self.assertEqual(payload["verdict"], verdict.UNVERIFIED)

    def test_results_compact_prints_one_line_per_task(self) -> None:
        import contextlib
        import io

        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        self.write_note()
        jobs.complete_task(self.root, "write-note", job_id=job["job_id"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            jobs.run(["results", "--compact", "--root", str(self.root)])
        lines = [line for line in buf.getvalue().splitlines() if line.strip()]
        self.assertEqual(lines, ["write-note passed 1/1"])

    def test_clean_all_removes_every_job_dir(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        jobs.start(self.root, dry_run=True)
        jobs.start(self.root, dry_run=True)
        removed = jobs.clean(self.root, all_jobs=True)
        self.assertEqual(len(removed), 2)
        self.assertEqual(list((self.root / ".gatekit" / "jobs").iterdir()), [])

    def test_clean_default_keeps_the_newest_job(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        jobs.start(self.root, dry_run=True)
        jobs.start(self.root, dry_run=True)
        jobs.clean(self.root)
        self.assertEqual(len(list((self.root / ".gatekit" / "jobs").iterdir())), 1)


# --------------------------------------------------------------------- gates


class TestRunGates(JobTestCase):
    def test_task_without_gates_is_unverified_and_never_passes(self) -> None:
        self.write_config()
        task = self.simple_task(gates=[])
        self.write_tasks(task)
        job = jobs.start(self.root)
        self.write_note()
        status = jobs.complete_task(self.root, "write-note", job_id=job["job_id"])
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["gates_verdict"], verdict.UNVERIFIED)

    def test_unrunnable_gate_argv_is_fail_not_crash(self) -> None:
        result = jobs.run_gates(self.root, {"gates": [
            {"name": "ghost", "argv": ["definitely-not-a-real-binary-xyz"]}]})
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertEqual(result["gates"][0]["verdict"], verdict.FAIL)

    def test_gate_stdout_and_stderr_tails_are_captured(self) -> None:
        result = jobs.run_gates(self.root, {"gates": [
            {"name": "exists", "argv": [sys.executable, str(GATE_EXISTS), "nope.txt"]}]})
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("missing: nope.txt", result["gates"][0]["stderr_tail"])

    def test_gates_run_sequentially_and_all_are_reported(self) -> None:
        (self.root / "a.txt").write_text("a", encoding="utf-8")
        result = jobs.run_gates(self.root, {"gates": [
            {"name": "one", "argv": [sys.executable, str(GATE_EXISTS), "a.txt"]},
            {"name": "two", "argv": [sys.executable, str(GATE_EXISTS), "b.txt"]},
        ]})
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["verdict"], verdict.FAIL)


class TestLoadTasks(JobTestCase):
    def test_tasks_come_from_fences_in_04_tasks(self) -> None:
        self.write_tasks(self.simple_task("a"), self.simple_task("b"))
        loaded = jobs.load_tasks(self.root)
        self.assertEqual([t["id"] for t in loaded], ["a", "b"])

    def test_missing_tasks_file_yields_empty_list(self) -> None:
        self.assertEqual(jobs.load_tasks(self.root), [])


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------------- design in the prompt


class TestDesignSection(JobTestCase):
    """ADR-0008 decision 4: the brief carries the design its task touches."""

    def write_tokens(self, data: dict) -> None:
        (self.root / "spec" / "tokens.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

    def v2(self, **kw) -> dict:
        data = {"version": 2, "source": [], "patterns": []}
        data.update(kw)
        return data

    def test_prompt_without_tokens_is_byte_identical_to_today(self) -> None:
        task = self.simple_task()
        before = jobs.build_prompt(task, "job-1")
        after = jobs.build_prompt(task, "job-1", root=self.root)
        self.assertEqual(before, after)
        self.assertNotIn("## Design", after)

    def test_unparsable_tokens_leaves_the_prompt_unchanged(self) -> None:
        (self.root / "spec" / "tokens.json").write_text("{nope", encoding="utf-8")
        task = self.simple_task()
        self.assertEqual(
            jobs.build_prompt(task, "job-1"),
            jobs.build_prompt(task, "job-1", root=self.root),
        )

    def test_design_section_sits_between_gates_and_reporting(self) -> None:
        self.write_tokens(self.v2(color={"primary": "#3366ff"}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        gates_at = prompt.index("## Gates that will judge this task")
        design_at = prompt.index("## Design")
        report_at = prompt.index("## Reporting")
        self.assertLess(gates_at, design_at)
        self.assertLess(design_at, report_at)

    def test_token_groups_are_rendered_as_group_dot_name_lines(self) -> None:
        self.write_tokens(self.v2(color={"primary": "#3366ff"}, space={"md": "16px"}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("color.primary: #3366ff", prompt)
        self.assertIn("space.md: 16px", prompt)

    def test_open_groups_need_no_code_change(self) -> None:
        self.write_tokens(self.v2(radius={"sm": "4px"}, motion={"fast": "120ms"}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("radius.sm: 4px", prompt)
        self.assertIn("motion.fast: 120ms", prompt)

    def test_object_token_with_a_value_key_renders_as_one_line(self) -> None:
        """`{"value": ..., "evidence": ...}` is one token, not two.

        The brief needs the value. `evidence` is bookkeeping for the spec
        reader, and rendering it as `color.primary.evidence` would read like a
        second token it could use.
        """
        self.write_tokens(self.v2(color={"primary": {"value": "#3366ff", "evidence": "preset:calm"}}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("color.primary: #3366ff", prompt)
        self.assertNotIn("color.primary.value", prompt)
        self.assertNotIn("preset:calm", prompt)

    def test_a_merged_preset_token_renders_as_its_value(self) -> None:
        """What `design merge-preset` writes must read correctly in a brief."""
        self.write_tokens(
            self.v2(
                source=["preset:calm"],
                color={"primary": "#aaaaaa", "accent": {"value": "#ff0000", "evidence": "preset:calm"}},
                radius={"md": {"value": "8px", "evidence": "preset:calm"}},
            )
        )
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("color.primary: #aaaaaa", prompt)
        self.assertIn("color.accent: #ff0000", prompt)
        self.assertIn("radius.md: 8px", prompt)
        self.assertNotIn(".evidence", prompt)

    def test_nested_object_without_a_value_key_still_recurses(self) -> None:
        self.write_tokens(self.v2(font={"body": {"size": "16px", "leading": "1.5"}}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("font.body.size: 16px", prompt)
        self.assertIn("font.body.leading: 1.5", prompt)

    def test_empty_tokens_object_leaves_the_prompt_unchanged(self) -> None:
        """A file holding `{}` carries no design, so it adds no section."""
        (self.root / "spec" / "tokens.json").write_text("{}", encoding="utf-8")
        task = self.simple_task()
        self.assertEqual(
            jobs.build_prompt(task, "job-1"),
            jobs.build_prompt(task, "job-1", root=self.root),
        )

    def test_tokens_with_no_groups_and_no_patterns_leaves_the_prompt_unchanged(self) -> None:
        self.write_tokens(self.v2(source=["figma.com/x"]))
        task = self.simple_task()
        self.assertEqual(
            jobs.build_prompt(task, "job-1"),
            jobs.build_prompt(task, "job-1", root=self.root),
        )

    def test_patterns_alone_are_enough_to_produce_a_section(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P1", "rule": "Cards in a list.", "applies_to": "all", "evidence": "x"}])
        )
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("## Design", prompt)

    def test_an_empty_group_alone_does_not_produce_a_section(self) -> None:
        self.write_tokens(self.v2(color={}))
        task = self.simple_task()
        self.assertEqual(
            jobs.build_prompt(task, "job-1"),
            jobs.build_prompt(task, "job-1", root=self.root),
        )

    def test_pattern_applying_to_all_is_always_included(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P1", "rule": "Cards in a list.", "applies_to": "all", "evidence": "x"}])
        )
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("- P1: Cards in a list. (applies to all)", prompt)

    def test_pattern_scoped_to_a_screen_the_task_names_is_included(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Bottom sheet on mobile.", "applies_to": ["S3"], "evidence": "x"}])
        )
        task = self.simple_task(instruction="Build the S3 detail view.")
        prompt = jobs.build_prompt(task, "job-1", root=self.root)
        self.assertIn("- P2: Bottom sheet on mobile. (applies to S3)", prompt)

    def test_pattern_scoped_to_a_screen_the_task_does_not_name_is_omitted(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Bottom sheet on mobile.", "applies_to": ["S9"], "evidence": "x"}])
        )
        task = self.simple_task(instruction="Build the S3 detail view.")
        self.assertNotIn("P2", jobs.build_prompt(task, "job-1", root=self.root))

    def test_screen_reference_in_the_title_counts(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Card grid.", "applies_to": ["S4"], "evidence": "x"}])
        )
        task = self.simple_task(title="S4 gallery", instruction="plain")
        self.assertIn("- P2: Card grid. (applies to S4)", jobs.build_prompt(task, "job-1", root=self.root))

    def test_zero_padded_applies_to_matches_the_unpadded_form(self) -> None:
        """`S01` in applies_to and `S1` in the task are the same screen.

        Missing the match loses the task a design rule silently, which is
        worse than a rule it did not need.
        """
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Card grid.", "applies_to": ["S01"], "evidence": "x"}])
        )
        task = self.simple_task(instruction="Build the S1 view.")
        self.assertIn("- P2: Card grid.", jobs.build_prompt(task, "job-1", root=self.root))

    def test_unpadded_applies_to_matches_a_padded_mention(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Card grid.", "applies_to": ["S1"], "evidence": "x"}])
        )
        task = self.simple_task(instruction="Build the S01 view.")
        self.assertIn("- P2: Card grid.", jobs.build_prompt(task, "job-1", root=self.root))

    def test_padding_does_not_make_different_screens_match(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Card grid.", "applies_to": ["S01"], "evidence": "x"}])
        )
        task = self.simple_task(instruction="Build the S10 view.")
        self.assertNotIn("P2", jobs.build_prompt(task, "job-1", root=self.root))

    def test_screen_match_respects_word_boundaries(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Card grid.", "applies_to": ["S1"], "evidence": "x"}])
        )
        task = self.simple_task(title="plain", instruction="Touch nothing in S12.")
        self.assertNotIn("P2", jobs.build_prompt(task, "job-1", root=self.root))

    def test_design_section_names_the_spec_files_to_read(self) -> None:
        self.write_tokens(self.v2(color={"primary": "#3366ff"}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn(
            "Read spec/02-design.md and spec/02-screens.md for anything not listed here.",
            prompt,
        )

    def test_v1_tokens_reach_the_prompt_too(self) -> None:
        self.write_tokens({"source": "figma", "color": {"primary": "#3366ff"}})
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("## Design", prompt)
        self.assertIn("color.primary: #3366ff", prompt)

    def test_reserved_keys_are_not_rendered_as_groups(self) -> None:
        self.write_tokens(self.v2(source=["figma"], color={"primary": "#3366ff"}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertNotIn("source.", prompt)
        self.assertNotIn("version", prompt.split("## Design")[1].split("## Reporting")[0])

    def test_screens_block_is_absent_without_a_screen_spec(self) -> None:
        self.write_tokens(self.v2(color={"primary": "#3366ff"}))
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build the S1 view."), "job-1", root=self.root
        )
        self.assertNotIn("## Screens", prompt)

    def test_start_threads_the_root_into_the_written_prompt(self) -> None:
        self.write_config()
        self.write_tokens(self.v2(color={"primary": "#3366ff"}))
        task = self.simple_task()
        self.write_tasks(task)
        job = jobs.start(self.root, dry_run=True)
        written = (self.task_dir(job["job_id"], "write-note") / "prompt.md").read_text(encoding="utf-8")
        self.assertIn("color.primary: #3366ff", written)


# ------------------------------------------------- screens in the prompt


SCREENS_MD = """# Tetris — screen spec

## Screen list

| Screen ID | Name | Feature | Evidence |
|---|---|---|---|
| S1 | Start | F3 | designed |
| S2 | Play | F1 | designed |

## Per-screen states

### S1 — Start

Layout: title at the top, three mode chips below, primary button under them.

| State | What is on screen | Evidence |
|---|---|---|
| normal | mode chips, start button, top-ten list | designed |
| empty | "no scores yet" line in place of the list | designed |

### S2 — Play

Layout: hold box on the left, score in the middle, next three on the right.

| State | What is on screen | Evidence |
|---|---|---|
| normal | board, active piece, ghost, touch controls | designed |
| empty | board empty, hold box dotted | designed |
"""


class TestScreensSection(JobTestCase):
    """ADR-0011 decision 3: the screen spec is pushed, not pointed at."""

    def write_tokens(self, data: dict) -> None:
        (self.root / "spec" / "tokens.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

    def write_screens(self, text: str = SCREENS_MD) -> None:
        (self.root / "spec" / "02-screens.md").write_text(text, encoding="utf-8")

    def setUp(self) -> None:
        super().setUp()
        self.write_tokens({"version": 2, "source": [], "patterns": [],
                           "color": {"primary": "#3366ff"}})

    def test_task_naming_a_screen_gets_that_screen_block(self) -> None:
        self.write_screens()
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build the S2 play view."), "job-1", root=self.root
        )
        self.assertIn("## Screens", prompt)
        self.assertIn("S2", prompt)
        self.assertIn("hold box on the left", prompt)

    def test_the_block_carries_the_state_rows(self) -> None:
        self.write_screens()
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build the S2 play view."), "job-1", root=self.root
        )
        self.assertIn("board, active piece, ghost, touch controls", prompt)
        self.assertIn("board empty, hold box dotted", prompt)

    def test_a_task_naming_no_screen_gets_no_block(self) -> None:
        self.write_screens()
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Write a pure module, no UI."), "job-1", root=self.root
        )
        self.assertNotIn("## Screens", prompt)

    def test_only_the_named_screen_is_carried(self) -> None:
        self.write_screens()
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build the S2 play view."), "job-1", root=self.root
        )
        block = prompt.split("## Screens")[1]
        self.assertIn("hold box on the left", block)
        self.assertNotIn("three mode chips", block)

    def test_a_task_naming_several_screens_carries_each(self) -> None:
        self.write_screens()
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build S1 and S2."), "job-1", root=self.root
        )
        self.assertIn("three mode chips", prompt)
        self.assertIn("hold box on the left", prompt)

    def test_screen_ids_respect_word_boundaries(self) -> None:
        self.write_screens()
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Nothing to do with S12 or S20."),
            "job-1", root=self.root,
        )
        self.assertNotIn("## Screens", prompt)

    def test_canonical_spelling_matches(self) -> None:
        self.write_screens()
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build the S02 play view."), "job-1", root=self.root
        )
        self.assertIn("hold box on the left", prompt)

    def test_screens_block_follows_the_design_section(self) -> None:
        self.write_screens()
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build the S2 play view."), "job-1", root=self.root
        )
        self.assertLess(prompt.index("## Design"), prompt.index("## Screens"))
        self.assertLess(prompt.index("## Screens"), prompt.index("## Reporting"))

    def test_unreadable_screen_spec_leaves_the_prompt_usable(self) -> None:
        (self.root / "spec" / "02-screens.md").write_text("", encoding="utf-8")
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build the S2 play view."), "job-1", root=self.root
        )
        self.assertNotIn("## Screens", prompt)
        self.assertIn("## Design", prompt)

    def test_a_screen_named_but_absent_from_the_spec_is_skipped(self) -> None:
        self.write_screens()
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build the S7 view."), "job-1", root=self.root
        )
        self.assertNotIn("## Screens", prompt)

    def test_screens_reach_the_written_prompt_through_start(self) -> None:
        self.write_screens()
        task = self.simple_task(instruction="Build the S2 play view.")
        self.write_tasks(task)
        job = jobs.start(self.root, dry_run=True)
        written = (self.task_dir(job["job_id"], "write-note") / "prompt.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("hold box on the left", written)


# ----------------------------------------------------- exit 3 is unverified


class TestGateExitThree(JobTestCase):
    """ADR-0008 decision 5 needs a gate that can say `unverified` by exit code."""

    def gate_exiting(self, code: int) -> dict:
        return {
            "name": "coded",
            "argv": [sys.executable, "-c", "import sys; sys.exit(%d)" % code],
        }

    def test_exit_three_is_unverified(self) -> None:
        result = jobs.run_gates(self.root, {"gates": [self.gate_exiting(3)]})
        self.assertEqual(result["gates"][0]["verdict"], verdict.UNVERIFIED)
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)

    def test_exit_three_detail_says_unverified(self) -> None:
        result = jobs.run_gates(self.root, {"gates": [self.gate_exiting(3)]})
        self.assertEqual(result["gates"][0]["detail"], "exit 3 (unverified)")
        self.assertEqual(result["gates"][0]["exit"], 3)

    def test_exit_zero_is_still_ok(self) -> None:
        result = jobs.run_gates(self.root, {"gates": [self.gate_exiting(0)]})
        self.assertEqual(result["gates"][0]["verdict"], verdict.OK)
        self.assertEqual(result["gates"][0]["detail"], "exit 0")

    def test_other_non_zero_exits_are_still_fail(self) -> None:
        for code in (1, 2, 4):
            result = jobs.run_gates(self.root, {"gates": [self.gate_exiting(code)]})
            self.assertEqual(result["gates"][0]["verdict"], verdict.FAIL, "exit %d" % code)
            self.assertEqual(result["gates"][0]["detail"], "exit %d" % code)

    def test_unverified_gate_is_not_counted_as_passed(self) -> None:
        result = jobs.run_gates(self.root, {"gates": [self.gate_exiting(3)]})
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["total"], 1)


# ------------------------------------------------------------ ADR-0009: preflight


FAIL_GATE = [sys.executable, "-c", "import sys; sys.exit(1)"]
PASS_GATE = [sys.executable, "-c", "print('always ok')"]


class TestPreflight(JobTestCase):
    def state(self, job: dict, task_id: str = "write-note") -> str:
        return json.loads((self.task_dir(job["job_id"], task_id) / "status.json").read_text())["state"]

    def test_a_gate_already_passing_marks_the_task_passed(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.write_note("already there")
        job = jobs.start(self.root)
        tdir = self.task_dir(job["job_id"], "write-note")
        status = json.loads((tdir / "status.json").read_text())
        self.assertEqual(status["state"], "passed")
        self.assertIn("preflight", status["detail"])
        self.assertEqual(job["plan"], [], "a task that already passes is not handed out")
        self.assertEqual((self.root / "src" / "note.txt").read_text(), "already there")
        self.assertTrue((tdir / "preflight.json").is_file())

    def test_command_error_gate_refuses_to_start(self) -> None:
        self.write_config()
        broken = self.simple_task(gates=[{"name": "broken",
                                          "argv": [sys.executable, "no-such-dir/"]}])
        self.write_tasks(broken)
        with self.assertRaises(jobs.GatePreflightError) as ctx:
            jobs.start(self.root)
        self.assertIn("broken", str(ctx.exception))
        self.assertIn("write-note", str(ctx.exception))
        self.assertFalse((self.root / "src" / "note.txt").exists())

    def test_command_error_cli_exits_nonzero_and_names_the_gate(self) -> None:
        import contextlib
        import io

        self.write_config()
        self.write_tasks(self.simple_task(gates=[{"name": "broken",
                                                  "argv": [sys.executable, "no-such-dir/"]}]))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = jobs.run(["start", "--root", str(self.root)])
        self.assertEqual(code, 4, "GatePreflightError has its own documented exit code")
        self.assertIn("broken", err.getvalue())

    def test_unverified_gate_at_preflight_is_expected_and_queues_the_task(self) -> None:
        self.write_config()
        cannot_judge = [sys.executable, "-c", "import sys; sys.exit(3)"]
        self.write_tasks(self.simple_task(gates=[{"name": "judge", "argv": cannot_judge}]))
        job = jobs.start(self.root)
        tdir = self.task_dir(job["job_id"], "write-note")
        pre = json.loads((tdir / "preflight.json").read_text())
        self.assertEqual(pre["verdict"], verdict.UNVERIFIED)
        self.assertEqual(job["preflight_warnings"], [])
        self.assertEqual(self.state(job), "queued")
        self.assertEqual([row["id"] for row in job["plan"]], ["write-note"])

    def test_expected_failure_still_queues_the_task(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        tdir = self.task_dir(job["job_id"], "write-note")
        pre = json.loads((tdir / "preflight.json").read_text())
        self.assertEqual(pre["verdict"], verdict.FAIL)
        self.assertEqual(self.state(job), "queued")
        self.assertEqual([row["id"] for row in job["plan"]], ["write-note"])

    def test_gate_passing_before_any_work_is_warned(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task(gates=[{"name": "always", "argv": PASS_GATE}]))
        job = jobs.start(self.root)
        status = json.loads(
            (self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        self.assertEqual(status["state"], "passed")
        self.assertIn("warn", status["detail"])
        self.assertIn("before any work", status["detail"])
        self.assertTrue(job.get("preflight_warnings"))

    def test_no_preflight_flag_skips_the_step(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.write_note("already there")
        job = jobs.start(self.root, no_preflight=True)
        tdir = self.task_dir(job["job_id"], "write-note")
        self.assertFalse((tdir / "preflight.json").exists())
        # the gate would pass, but nothing ran it: the task waits for `complete`
        self.assertEqual(self.state(job), "queued")
        saved = json.loads((self.root / ".gatekit" / "jobs" / job["job_id"] / "job.json").read_text())
        self.assertTrue(saved["no_preflight"])

    def test_suspicious_gate_starts_the_job_with_a_warning(self) -> None:
        self.write_config()
        suspicious = [sys.executable, "-c", "import sys; sys.stderr.write('usage: x\\n'); sys.exit(2)"]
        self.write_tasks(self.simple_task(gates=[{"name": "odd", "argv": suspicious}]))
        job = jobs.start(self.root)  # must not raise
        self.assertTrue(any("odd" in w and "starting anyway" in w
                            for w in job["preflight_warnings"]))
        self.assertEqual(self.state(job), "queued")

    def test_dry_run_does_not_preflight(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task(gates=[{"name": "broken",
                                                  "argv": [sys.executable, "no-such-dir/"]}]))
        job = jobs.start(self.root, dry_run=True)  # must not raise
        self.assertFalse(
            (self.task_dir(job["job_id"], "write-note") / "preflight.json").exists())


class TestLooksLikeCommandError(unittest.TestCase):
    NODE_ARGV = ["node", "--test", "tetris/tests/rules/"]
    PY_ARGV = ["python3", "no-such-dir/"]

    def _gate(self, exit_code, stdout="", stderr=""):
        return {"name": "g", "verdict": verdict.FAIL, "exit": exit_code,
                "stdout_tail": stdout, "stderr_tail": stderr}

    def test_exit_one_with_plain_test_failure_is_expected(self) -> None:
        self.assertEqual(jobs.classify_gate_result(self._gate(1, "1 test failed"), self.NODE_ARGV),
                         "expected")

    def test_missing_module_naming_an_argument_is_a_command_error(self) -> None:
        gate = self._gate(1, "Error: Cannot find module '/x/tetris/tests/rules'")
        self.assertTrue(jobs.looks_like_command_error(gate, self.NODE_ARGV))

    def test_interpreter_cannot_open_the_argument_is_a_command_error(self) -> None:
        gate = self._gate(2, "", "python3: can't open file '/x/no-such-dir/': [Errno 2] No such file or directory")
        self.assertTrue(jobs.looks_like_command_error(gate, self.PY_ARGV))

    def test_missing_fixture_inside_test_output_is_not_a_command_error(self) -> None:
        # A real failing test that mentions some other missing file: the
        # message names nothing from argv, so the job must still start.
        gate = self._gate(1, "FAIL: open('fixtures/data.json'): No such file or directory")
        self.assertFalse(jobs.looks_like_command_error(gate, self.NODE_ARGV))
        self.assertEqual(jobs.classify_gate_result(gate, self.NODE_ARGV), "suspicious")

    def test_exit_two_alone_is_suspicious_not_refused(self) -> None:
        gate = self._gate(2, "", "2 errors during collection")
        self.assertFalse(jobs.looks_like_command_error(gate, ["pytest", "tests/"]))
        self.assertEqual(jobs.classify_gate_result(gate, ["pytest", "tests/"]), "suspicious")

    def test_usage_banner_is_suspicious_not_refused(self) -> None:
        gate = self._gate(2, "", "usage: foo [-h]")
        self.assertEqual(jobs.classify_gate_result(gate, ["foo"]), "suspicious")

    def test_usage_inside_test_output_is_expected(self) -> None:
        gate = self._gate(1, "captured stdout:\nusage: app [--flag]\n1 failed")
        self.assertEqual(jobs.classify_gate_result(gate, self.NODE_ARGV), "expected")

    def test_shell_not_found_exit_codes_are_command_errors(self) -> None:
        for code in (126, 127):
            self.assertTrue(jobs.looks_like_command_error(self._gate(code), ["nope"]))

    def test_command_not_found_naming_the_program_is_a_command_error(self) -> None:
        gate = self._gate(1, "", "sh: npx: command not found")
        self.assertTrue(jobs.looks_like_command_error(gate, ["npx", "tsc"]))

    def test_ok_and_unverified_are_never_command_errors(self) -> None:
        for v in (verdict.OK, verdict.UNVERIFIED):
            gate = {"name": "g", "verdict": v, "exit": 127, "stdout_tail": "", "stderr_tail": ""}
            self.assertFalse(jobs.looks_like_command_error(gate, ["nope"]))
            self.assertEqual(jobs.classify_gate_result(gate, ["nope"]), "expected")

    def test_malformed_gate_dict_is_not_a_command_error(self) -> None:
        self.assertFalse(jobs.looks_like_command_error({}))
        self.assertFalse(jobs.looks_like_command_error({"verdict": verdict.FAIL, "exit": None}))

    def test_missing_argv_still_classifies_by_exit_code(self) -> None:
        self.assertTrue(jobs.looks_like_command_error(self._gate(127), argv=None))
        self.assertEqual(jobs.classify_gate_result(self._gate(1, "Cannot find module 'x'"), None),
                         "suspicious")


# ---------------------------------------------------------------- ADR-0009: stop


class TestStop(JobTestCase):
    """`jobs stop` ends a job the session will not finish. A job starts no process,
    so stopping is bookkeeping: unfinished tasks become `stopped`."""

    def test_stopped_counts_as_not_done_and_fail(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        jobs.stop(self.root, job["job_id"])
        payload = jobs.status(self.root, job["job_id"])
        self.assertEqual(payload["verdict"], verdict.FAIL)
        self.assertTrue(payload["done"])
        self.assertEqual(payload["tasks"][0]["state"], "stopped")

    def test_stop_marks_only_the_unfinished_tasks_and_records_when(self) -> None:
        self.write_config()
        second = self.simple_task(task_id="second", target="src/second.txt", round=2)
        self.write_tasks(self.simple_task(), second)
        job = jobs.start(self.root)
        self.write_note()
        jobs.complete_task(self.root, "write-note", job_id=job["job_id"])
        result = jobs.stop(self.root, job["job_id"])
        self.assertEqual(result, {"job_id": job["job_id"], "stopped": ["second"]})
        st1 = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        st2 = json.loads((self.task_dir(job["job_id"], "second") / "status.json").read_text())
        self.assertEqual((st1["state"], st2["state"]), ("passed", "stopped"))
        saved = json.loads((self.root / ".gatekit" / "jobs" / job["job_id"] / "job.json").read_text())
        self.assertIn("stopped_at", saved)
        # the job is closed there and then: the prompt hook names a job as the live build
        # until it carries `finished_at`
        self.assertIn("finished_at", saved)

    def test_stop_without_a_job_raises(self) -> None:
        with self.assertRaises(ValueError):
            jobs.stop(self.root, None)

    def test_stop_survives_a_malformed_status_file(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        tdir = self.task_dir(job["job_id"], "write-note")
        (tdir / "status.json").write_text("{not json", encoding="utf-8")
        result = jobs.stop(self.root, job["job_id"])  # must not raise
        self.assertIn("write-note", result["stopped"])

    def test_cli_stop_says_how_many_tasks_it_stopped(self) -> None:
        import contextlib
        import io

        self.write_config()
        self.write_tasks(self.simple_task())
        jobs.start(self.root, dry_run=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = jobs.run(["stop", "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("1 task(s) marked stopped", out.getvalue())
        self.assertNotIn("signalled", out.getvalue())


# ----------------------------------------- states only an older job folder holds


class TestStatesFromOlderJobs(JobTestCase):
    """No command produces `blocked` (or `timeout`, `running`, `gating`) any more, but a job
    folder written by an older kit may hold them, and it must still be read correctly."""

    def test_blocked_alone_makes_the_job_unverified_not_fail(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task(), self.simple_task(task_id="second", target="src/s.txt"))
        job = jobs.start(self.root, dry_run=True)
        jdir = self.root / ".gatekit" / "jobs" / job["job_id"]
        jobs._set_status(jdir, "write-note", state="passed")
        jobs._set_status(jdir, "second", state="blocked",
                         detail="dependency x ended before this task could run")
        payload = jobs.status(self.root, job["job_id"])
        self.assertEqual(payload["verdict"], verdict.UNVERIFIED)
        self.assertTrue(payload["done"])


class TestScreensParserRobustness(JobTestCase):
    """Review findings on ADR-0011 decision 3: silent wrong output is the
    worst failure for a feature whose only job is spec-to-brief fidelity."""

    def write_tokens(self) -> None:
        (self.root / "spec" / "tokens.json").write_text(
            json.dumps({"version": 2, "source": [], "patterns": [],
                        "color": {"primary": "#3366ff"}}), encoding="utf-8"
        )

    def write_screens(self, text: str) -> None:
        (self.root / "spec" / "02-screens.md").write_text(text, encoding="utf-8")

    def setUp(self) -> None:
        super().setUp()
        self.write_tokens()

    def test_a_fence_does_not_amputate_the_following_state_rows(self) -> None:
        self.write_screens(
            "### S1 — Start\n\n"
            "Layout: title top, chips below.\n\n"
            "```\n"
            "### S9 — a heading drawn inside a diagram\n"
            "| S1 | -> | S2 |\n"
            "```\n\n"
            "| State | What |\n|---|---|\n"
            "| normal | chips and start button |\n"
        )
        screens = jobs.parse_screens(
            (self.root / "spec" / "02-screens.md").read_text(encoding="utf-8")
        )
        self.assertEqual(list(screens), ["S1"])
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build S1."), "job-1", root=self.root
        )
        self.assertIn("chips and start button", prompt)

    def test_a_heading_inside_a_fence_makes_no_screen(self) -> None:
        self.write_screens(
            "### S1 — Start\n\nLayout: a.\n\n```\n### S9 — drawn\n```\n"
        )
        self.assertEqual(
            list(jobs.parse_screens(
                (self.root / "spec" / "02-screens.md").read_text(encoding="utf-8"))),
            ["S1"],
        )

    def test_a_tilde_fence_is_handled_too(self) -> None:
        self.write_screens(
            "### S1 — Start\n\nLayout: a.\n\n~~~\n### S9 — drawn\n~~~\n\n"
            "| State | What |\n|---|---|\n| normal | real row |\n"
        )
        screens = jobs.parse_screens(
            (self.root / "spec" / "02-screens.md").read_text(encoding="utf-8"))
        self.assertEqual(list(screens), ["S1"])
        self.assertIn(["normal", "real row"], screens["S1"]["states"][1:])

    def test_an_escaped_pipe_keeps_the_whole_description(self) -> None:
        self.write_screens(
            "### S1 — Start\n\nLayout: a.\n\n"
            "| State | What |\n|---|---|\n"
            "| normal | press A \\| B to choose |\n"
        )
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build S1."), "job-1", root=self.root
        )
        self.assertIn("press A | B to choose", prompt)

    def test_a_very_long_layout_is_truncated(self) -> None:
        self.write_screens(
            "### S1 — Start\n\nLayout: " + ("x" * 50_000) + "\n\n"
            "| State | What |\n|---|---|\n| normal | ok |\n"
        )
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build S1."), "job-1", root=self.root
        )
        self.assertLess(len(prompt), 20_000)
        self.assertIn("…", prompt)

    def test_many_screens_stay_within_the_block_budget(self) -> None:
        body = ""
        for n in range(1, 13):
            body += "### S%d — Screen %d\n\nLayout: %s\n\n" % (n, n, "y" * 3000)
            body += "| State | What |\n|---|---|\n| normal | %s |\n\n" % ("z" * 3000)
        self.write_screens(body)
        names = " ".join("S%d" % n for n in range(1, 13))
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build " + names), "job-1", root=self.root
        )
        block = prompt.split("## Screens")[1].split("## Reporting")[0]
        self.assertLess(len(block), jobs.SCREENS_BLOCK_MAX_CHARS + 2000)

    def test_screens_block_needs_no_tokens_file(self) -> None:
        (self.root / "spec" / "tokens.json").unlink()
        self.write_screens(
            "### S1 — Start\n\nLayout: title on top.\n\n"
            "| State | What |\n|---|---|\n| normal | ok |\n"
        )
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Build S1."), "job-1", root=self.root
        )
        self.assertIn("## Screens", prompt)
        self.assertIn("title on top", prompt)

    def test_word_boundaries_reject_an_embedded_id(self) -> None:
        self.write_screens(
            "### S1 — Start\n\nLayout: a.\n\n| State | What |\n|---|---|\n| normal | ok |\n"
        )
        prompt = jobs.build_prompt(
            self.simple_task(instruction="Touch PS1TUTE and XS1 only."),
            "job-1", root=self.root,
        )
        self.assertNotIn("## Screens", prompt)


class TestStopJobJsonRace(JobTestCase):
    """`stop` (`stopped_at`) and `status` (`finished_at`) both write job.json;
    neither may erase the other's field, whichever held an older copy."""

    def test_stop_does_not_erase_a_concurrent_finished_at(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        jdir = self.root / ".gatekit" / "jobs" / job["job_id"]
        # `status` stamped finished_at after `stop` read job.json.
        stale = jobs.read_json(jdir / "job.json", {})
        current = dict(stale)
        current["finished_at"] = "2026-09-17T09:00:00Z"
        jobs.write_json(jdir / "job.json", current)
        jobs.stop(self.root, job["job_id"])
        saved = jobs.read_json(jdir / "job.json", {})
        self.assertIn("stopped_at", saved)
        self.assertEqual(saved.get("finished_at"), "2026-09-17T09:00:00Z")

    def test_finishing_after_stop_keeps_stopped_at(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        jdir = self.root / ".gatekit" / "jobs" / job["job_id"]
        jobs.stop(self.root, job["job_id"])
        # A `status` call holding a pre-stop copy finalises now.
        jobs._finalise_job(jdir, dict(job))
        saved = jobs.read_json(jdir / "job.json", {})
        self.assertIn("stopped_at", saved)
        self.assertIn("finished_at", saved)


# ------------------------------------------- ADR-0013: recheck without a rebuild


class TestGatesRecheck(JobTestCase):
    """A gate edit must cost a gate run, not a rebuild.

    On gk-trial2 (2026-09-17) 28 of 35 task runs existed only because a
    gate was refined; the code was already correct. Re-running the gate is
    seconds, re-deriving the code is minutes.
    """

    def retarget(self, task_id: str, argv: list) -> None:
        """Rewrite one task's gate in spec/04-tasks.md, as an operator would."""
        task = self.simple_task(task_id=task_id)
        task["gates"] = [{"name": "check", "argv": argv}]
        self.write_tasks(task)

    def test_recheck_marks_a_task_passed_without_a_new_job(self) -> None:
        self.write_config()
        task = self.simple_task()
        self.write_tasks(task)
        job = jobs.start(self.root, dry_run=True)
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "note.txt").write_text("done", encoding="utf-8")
        result = jobs.recheck(self.root, job_id=job["job_id"])
        self.assertEqual(result["rechecked"], ["write-note"])
        st = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        self.assertEqual(st["state"], "passed")
        self.assertIn("recheck", st["detail"])
        self.assertEqual(jobs.latest_job_id(self.root), job["job_id"])

    def test_recheck_reads_the_current_task_file_not_the_snapshot(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        # The operator narrows the gate to something that passes right now.
        self.retarget("write-note", [sys.executable, "-c", "import sys; sys.exit(0)"])
        result = jobs.recheck(self.root, job_id=job["job_id"])
        st = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        self.assertEqual(st["state"], "passed")
        self.assertIn("write-note", result["rechecked"])

    def test_a_still_failing_gate_leaves_the_task_failed(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        jobs.recheck(self.root, job_id=job["job_id"])
        st = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        self.assertEqual(st["state"], "failed")

    def test_an_unverified_gate_does_not_round(self) -> None:
        self.write_config()
        task = self.simple_task()
        task["gates"] = [{"name": "u", "argv": [sys.executable, "-c", "import sys; sys.exit(3)"]}]
        self.write_tasks(task)
        job = jobs.start(self.root, dry_run=True)
        jobs.recheck(self.root, job_id=job["job_id"])
        st = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        self.assertEqual(st["gates_verdict"], verdict.UNVERIFIED)
        self.assertNotEqual(st["state"], "passed")

    def test_one_task_can_be_named(self) -> None:
        self.write_config()
        first = self.simple_task()
        second = self.simple_task(task_id="second", target="src/second.txt")
        self.write_tasks(first, second)
        job = jobs.start(self.root, dry_run=True)
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "note.txt").write_text("x", encoding="utf-8")
        (self.root / "src" / "second.txt").write_text("x", encoding="utf-8")
        result = jobs.recheck(self.root, task_ids=["write-note"], job_id=job["job_id"])
        self.assertEqual(result["rechecked"], ["write-note"])
        st2 = json.loads((self.task_dir(job["job_id"], "second") / "status.json").read_text())
        self.assertNotEqual(st2["state"], "passed")

    def test_recheck_writes_gates_json(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "note.txt").write_text("x", encoding="utf-8")
        jobs.recheck(self.root, job_id=job["job_id"])
        gates = json.loads((self.task_dir(job["job_id"], "write-note") / "gates.json").read_text())
        self.assertEqual(gates["verdict"], verdict.OK)

    def test_a_task_removed_from_the_file_is_reported_not_crashed(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        self.write_tasks(self.simple_task(task_id="renamed", target="src/other.txt"))
        result = jobs.recheck(self.root, job_id=job["job_id"])
        self.assertIn("write-note", result["missing"])

    def test_no_job_is_a_clear_error(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        with self.assertRaises(ValueError):
            jobs.recheck(self.root)

    def test_recheck_never_touches_a_passed_task_state_wrongly(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "note.txt").write_text("x", encoding="utf-8")
        jobs.recheck(self.root, job_id=job["job_id"])
        first = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        jobs.recheck(self.root, job_id=job["job_id"])
        second = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        self.assertEqual(first["state"], second["state"])
        self.assertEqual(second["state"], "passed")

    def test_cli_recheck_exits_zero_on_pass(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        jobs.start(self.root, dry_run=True)
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "note.txt").write_text("x", encoding="utf-8")
        code = jobs.run(["recheck", "--root", str(self.root)])
        self.assertEqual(code, 0)

    def test_cli_recheck_exits_one_on_fail(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        jobs.start(self.root, dry_run=True)
        self.assertEqual(jobs.run(["recheck", "--root", str(self.root)]), 1)

    def test_cli_recheck_accepts_a_task_name(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        jobs.start(self.root, dry_run=True)
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "note.txt").write_text("x", encoding="utf-8")
        self.assertEqual(
            jobs.run(["recheck", "write-note", "--root", str(self.root)]), 0
        )

    def test_cli_recheck_without_a_job_exits_two(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.assertEqual(jobs.run(["recheck", "--root", str(self.root)]), 2)


# ------------------------------------ ADR-0013 decision 1: host execution


class TestHostExecution(JobTestCase):
    """The session that already knows the project implements the task.

    `start` prepares the job and hands back the plan; `complete_task` runs the
    gates. On gk-trial2 a separate cold session was started for every task, 35
    times, while a session that knew the repo waited. Every gate, verdict and
    scope rule stays; only who holds the editor changed.
    """

    def host_config(self) -> None:
        self.write_config()

    def test_start_prepares_the_job_and_starts_nothing(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        tdir = self.task_dir(job["job_id"], "write-note")
        self.assertTrue((tdir / "task.json").is_file())
        self.assertTrue((tdir / "prompt.md").is_file())
        self.assertFalse((tdir / "gates.json").exists(), "no gate verdict before `complete`")
        self.assertFalse((self.root / "src" / "note.txt").exists())

    def test_start_leaves_tasks_awaiting_the_host(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        st = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        self.assertEqual(st["state"], "queued")
        self.assertIn("host", st["detail"])

    def test_start_returns_the_ordered_plan(self) -> None:
        self.host_config()
        first = self.simple_task()
        second = self.simple_task(task_id="second", target="src/second.txt",
                                  round=2, depends_on=["write-note"])
        self.write_tasks(first, second)
        job = jobs.start(self.root)
        self.assertEqual([r["id"] for r in job["plan"]], ["write-note", "second"])
        self.assertEqual(job["plan"][0]["round"], 1)

    def test_a_host_task_passes_through_the_same_gates(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        self.write_note()
        st = jobs.complete_task(self.root, "write-note", job_id=job["job_id"])
        self.assertEqual(st["state"], "passed")
        self.assertEqual(st["gates_passed"], 1)

    def test_a_host_task_that_fails_its_gate_is_failed(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        st = jobs.complete_task(self.root, "write-note", job_id=job["job_id"])
        self.assertEqual(st["state"], "failed")
        self.assertNotEqual(st["state"], "passed")

    def test_unverified_does_not_round_in_host_mode(self) -> None:
        self.host_config()
        task = self.simple_task()
        task["gates"] = [{"name": "u", "argv": [sys.executable, "-c", "import sys; sys.exit(3)"]}]
        self.write_tasks(task)
        job = jobs.start(self.root)
        st = jobs.complete_task(self.root, "write-note", job_id=job["job_id"])
        self.assertEqual(st["gates_verdict"], verdict.UNVERIFIED)
        self.assertNotEqual(st["state"], "passed")

    def test_completing_an_unknown_task_is_refused(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        with self.assertRaises(ValueError):
            jobs.complete_task(self.root, "nope", job_id=job["job_id"])

    def test_host_mode_still_runs_preflight(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        self.write_note("already")
        job = jobs.start(self.root)
        st = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        self.assertEqual(st["state"], "passed")
        self.assertIn("preflight", st["detail"])

    def test_cli_complete_records_the_verdict(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        jobs.start(self.root)
        self.write_note("x")
        self.assertEqual(
            jobs.run(["complete", "write-note", "--root", str(self.root)]), 0
        )

    def test_cli_complete_exits_one_when_gates_fail(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        jobs.start(self.root)
        self.assertEqual(
            jobs.run(["complete", "write-note", "--root", str(self.root)]), 1
        )

    def test_cli_complete_without_a_task_exits_two(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        jobs.start(self.root)
        self.assertEqual(jobs.run(["complete", "--root", str(self.root)]), 2)

    def test_cli_start_prints_the_job_line_and_the_waiting_task(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = jobs.run(["start", "--root", str(self.root)])
        self.assertEqual(code, 0)
        # the first line is quoted in build-notice.md: no program name in it any more
        self.assertRegex(out.getvalue(), r"^job \S+  verdict=unverified\n")
        self.assertIn("awaiting the host session", out.getvalue())
        self.assertNotIn("backend", out.getvalue())


# ------------------------------- ADR-0013 decision 4: show the shape first


class TestTaskShape(JobTestCase):
    """`/gatekit-tasks` must show rounds as prominently as the count.

    On gk-trial2 nine tasks — a reasonable number — were spread over seven
    rounds, five of them holding one task. The count alone would have looked
    fine; rounds are what cost the time.
    """

    def shape_for(self, *tasks) -> dict:
        self.write_tasks(*tasks)
        return jobs.shape(self.root)

    def test_it_counts_tasks_and_rounds(self) -> None:
        shape = self.shape_for(
            self.simple_task(task_id="a", target="src/a.txt"),
            self.simple_task(task_id="b", target="src/b.txt", depends_on=["a"], round=2))
        self.assertEqual(shape["tasks"], 2)
        self.assertEqual(shape["rounds"], 2)

    def test_independent_tasks_share_a_round(self) -> None:
        shape = self.shape_for(
            self.simple_task(task_id="a", target="src/a.txt"),
            self.simple_task(task_id="b", target="src/b.txt"),
            self.simple_task(task_id="c", target="src/c.txt"))
        self.assertEqual(shape["rounds"], 1)
        self.assertEqual(len(shape["waves"][0]), 3)

    def test_it_flags_dependencies_with_no_file_evidence(self) -> None:
        a = self.simple_task(task_id="schema-setup", target="src/alpha.ts")
        b = self.simple_task(task_id="ui-shell", target="src/beta.ts",
                             depends_on=["schema-setup"], round=2)
        b["instruction"] = "Write the shell. It stands on its own."
        shape = self.shape_for(a, b)
        self.assertEqual(shape["unevidenced"], [["ui-shell", "schema-setup"]])

    def test_a_dependency_named_in_the_instruction_is_evidenced(self) -> None:
        a = self.simple_task(task_id="a", target="src/alpha.ts")
        b = self.simple_task(task_id="b", target="src/beta.ts",
                             depends_on=["a"], round=2)
        b["instruction"] = "Import the helper from src/alpha.ts and extend it."
        shape = self.shape_for(a, b)
        self.assertEqual(shape["unevidenced"], [])

    def test_it_reports_the_rounds_without_unevidenced_dependencies(self) -> None:
        """The number that matters: what the plan costs once the links nobody
        can justify are dropped. On gk-trial2 that was seven rounds to three."""
        a = self.simple_task(task_id="schema-setup", target="src/alpha.ts")
        b = self.simple_task(task_id="ui-shell", target="src/beta.ts",
                             depends_on=["schema-setup"], round=2)
        b["instruction"] = "Write the shell. It stands on its own."
        c = self.simple_task(task_id="digest-view", target="src/gamma.ts",
                             depends_on=["ui-shell"], round=3)
        c["instruction"] = "Write the digest view. It stands on its own."
        shape = self.shape_for(a, b, c)
        self.assertEqual(shape["rounds"], 3)
        self.assertEqual(shape["rounds_if_pruned"], 1)

    def test_a_task_naming_the_dependency_id_counts_as_evidence(self) -> None:
        a = self.simple_task(task_id="core-rules", target="src/rules.ts")
        b = self.simple_task(task_id="b", target="src/b.ts",
                             depends_on=["core-rules"], round=2)
        b["instruction"] = "Build on what core-rules produced."
        self.assertEqual(self.shape_for(a, b)["unevidenced"], [])

    def test_the_critical_path_uses_the_widest_round(self) -> None:
        shape = self.shape_for(
            self.simple_task(task_id="a", target="src/a.txt"),
            self.simple_task(task_id="b", target="src/b.txt"),
            self.simple_task(task_id="c", target="src/c.txt", depends_on=["a"], round=2))
        self.assertEqual(shape["rounds"], 2)
        self.assertEqual(shape["serial"], 3)

    def test_no_tasks_is_a_clear_error(self) -> None:
        (self.root / "spec" / "04-tasks.md").write_text("# Tasks\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            jobs.shape(self.root)

    def test_cli_shape_prints_rounds(self) -> None:
        self.write_tasks(
            self.simple_task(task_id="a", target="src/a.txt"),
            self.simple_task(task_id="b", target="src/b.txt", depends_on=["a"], round=2))
        self.assertEqual(jobs.run(["shape", "--root", str(self.root)]), 0)


# ------------------- ADR-0014: attempts are counted per task, not per job


class TestAttemptLedger(JobTestCase):
    """On gk-trial2 one task failed eight times and the budget never fired:
    `start` writes attempt=1, so every new job reset the counter. The count
    now lives with the task."""

    def ledger(self) -> dict:
        return jobs.read_json(self.root / ".gatekit" / "attempts.json", {}) or {}

    def failures(self, task_id: str) -> int:
        return int(((self.ledger().get("tasks") or {}).get(task_id) or {})
                   .get("failures", 0))

    def test_a_failure_is_recorded(self) -> None:
        jobs.record_attempt(self.root, "t", "failed", job_id="j1", gate="g")
        self.assertEqual(self.failures("t"), 1)

    def test_failures_accumulate_across_jobs(self) -> None:
        for job in ("j1", "j2", "j3"):
            jobs.record_attempt(self.root, "t", "failed", job_id=job)
        self.assertEqual(self.failures("t"), 3)

    def test_a_pass_clears_the_count(self) -> None:
        jobs.record_attempt(self.root, "t", "failed", job_id="j1")
        jobs.record_attempt(self.root, "t", "passed", job_id="j2")
        self.assertEqual(self.failures("t"), 0)

    def test_blocked_and_stopped_do_not_count(self) -> None:
        jobs.record_attempt(self.root, "t", "failed", job_id="j1")
        jobs.record_attempt(self.root, "t", "blocked", job_id="j2")
        jobs.record_attempt(self.root, "t", "stopped", job_id="j3")
        self.assertEqual(self.failures("t"), 1)

    def test_a_timeout_counts_as_a_failure(self) -> None:
        jobs.record_attempt(self.root, "t", "timeout", job_id="j1")
        self.assertEqual(self.failures("t"), 1)

    def test_tasks_are_counted_separately(self) -> None:
        jobs.record_attempt(self.root, "a", "failed", job_id="j1")
        jobs.record_attempt(self.root, "b", "failed", job_id="j1")
        jobs.record_attempt(self.root, "a", "failed", job_id="j2")
        self.assertEqual((self.failures("a"), self.failures("b")), (2, 1))

    def test_the_entry_remembers_where_it_failed(self) -> None:
        jobs.record_attempt(self.root, "t", "failed", job_id="j9", gate="e2e")
        entry = (self.ledger().get("tasks") or {}).get("t") or {}
        self.assertEqual(entry.get("last_job"), "j9")
        self.assertEqual(entry.get("last_gate"), "e2e")

    def test_a_corrupt_file_behaves_as_empty(self) -> None:
        (self.root / ".gatekit" / "attempts.json").write_text("{nope", encoding="utf-8")
        self.assertEqual(jobs.consecutive_failures(self.root, "t"), 0)
        jobs.record_attempt(self.root, "t", "failed", job_id="j1")
        self.assertEqual(self.failures("t"), 1)

    def test_force_retry_clears_one_task_only(self) -> None:
        jobs.record_attempt(self.root, "a", "failed", job_id="j1")
        jobs.record_attempt(self.root, "b", "failed", job_id="j1")
        jobs.clear_attempts(self.root, "a")
        self.assertEqual((self.failures("a"), self.failures("b")), (0, 1))


class TestBudgetBindsAcrossJobs(JobTestCase):
    def exhaust(self, task_id: str = "write-note") -> None:
        for job in ("j1", "j2"):
            jobs.record_attempt(self.root, task_id, "failed", job_id=job, gate="g")

    def test_start_refuses_a_task_at_the_limit(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.exhaust()
        with self.assertRaises(jobs.RetryBudgetExceeded):
            jobs.start(self.root)

    def test_the_refusal_names_the_task_and_the_count(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.exhaust()
        try:
            jobs.start(self.root)
            self.fail("expected a refusal")
        except jobs.RetryBudgetExceeded as exc:
            self.assertIn("write-note", str(exc))
            self.assertIn("2", str(exc))

    def test_start_runs_a_task_below_the_limit(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        jobs.record_attempt(self.root, "write-note", "failed", job_id="j1")
        job = jobs.start(self.root, dry_run=True)
        self.assertIn("write-note", job["tasks"])

    def test_force_retry_lets_start_proceed(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.exhaust()
        jobs.clear_attempts(self.root, "write-note")
        job = jobs.start(self.root, dry_run=True)
        self.assertIn("write-note", job["tasks"])

    def test_a_passing_task_frees_the_budget_again(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.exhaust()
        jobs.record_attempt(self.root, "write-note", "passed", job_id="j3")
        job = jobs.start(self.root, dry_run=True)
        self.assertIn("write-note", job["tasks"])

    def test_cli_start_exits_three_when_refused(self) -> None:
        """Exit 3 means "out of retries": a script sees one signal for it."""
        self.write_config()
        self.write_tasks(self.simple_task())
        self.exhaust()
        self.assertEqual(jobs.run(["start", "--root", str(self.root)]), 3)

    def test_cli_force_retry_clears_and_starts(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.exhaust()
        code = jobs.run(["start", "--force-retry", "write-note",
                         "--root", str(self.root)])
        self.assertEqual(code, 0)


class TestAttemptWiring(JobTestCase):
    """The counter must see the same events the status file does."""

    def failures(self, task_id: str) -> int:
        return jobs.consecutive_failures(self.root, task_id)

    def test_a_passing_complete_clears_it(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        jobs.record_attempt(self.root, "write-note", "failed", job_id="old")
        job = jobs.start(self.root)
        self.write_note()
        jobs.complete_task(self.root, "write-note", job_id=job["job_id"])
        self.assertEqual(self.failures("write-note"), 0)

    def test_complete_task_counts_as_an_attempt(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())   # gate fails: no file written
        job = jobs.start(self.root)
        jobs.complete_task(self.root, "write-note", job_id=job["job_id"])
        self.assertEqual(self.failures("write-note"), 1)

    def test_recheck_does_not_count_as_an_attempt(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        jobs.recheck(self.root, job_id=job["job_id"])
        self.assertEqual(self.failures("write-note"), 0)


class TestStatusShowsCarriedCount(JobTestCase):
    def test_status_reports_consecutive_failures(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        jobs.record_attempt(self.root, "write-note", "failed", job_id="old1")
        job = jobs.start(self.root, dry_run=True)
        payload = jobs.status(self.root, job["job_id"])
        row = payload["tasks"][0]
        self.assertEqual(row["consecutive_failures"], 1)

    def test_table_shows_the_count_when_it_exceeds_the_in_job_attempt(self) -> None:
        import contextlib, io
        self.write_config()
        self.write_tasks(self.simple_task())
        jobs.record_attempt(self.root, "write-note", "failed", job_id="old1")
        job = jobs.start(self.root, dry_run=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            jobs.run(["status", "--job", job["job_id"], "--root", str(self.root)])
        self.assertIn("1 consecutive", out.getvalue())

    def test_table_says_nothing_when_the_count_is_not_ahead(self) -> None:
        import contextlib, io
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            jobs.run(["status", "--job", job["job_id"], "--root", str(self.root)])
        self.assertNotIn("consecutive", out.getvalue())


class TestHostExecutionFinishesJob(JobTestCase):
    """`start()` returns right after handing back the plan, so nothing there
    calls `_finalise_job`. Found via a real gk-trial2 retrial
    where `job.json.finished_at` stayed empty despite every task passing."""

    def host_config(self) -> None:
        self.write_config()

    def test_finished_at_is_absent_right_after_start(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        saved = json.loads(
            (self.root / ".gatekit" / "jobs" / job["job_id"] / "job.json").read_text())
        self.assertNotIn("finished_at", saved)

    def test_status_stamps_finished_at_once_every_task_is_terminal(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "note.txt").write_text("done", encoding="utf-8")
        jobs.complete_task(self.root, "write-note", job_id=job["job_id"])
        payload = jobs.status(self.root, job["job_id"])
        self.assertTrue(payload["done"])
        self.assertIsNotNone(payload["finished_at"])
        saved = json.loads(
            (self.root / ".gatekit" / "jobs" / job["job_id"] / "job.json").read_text())
        self.assertIn("finished_at", saved)

    def test_finished_at_is_not_stamped_while_a_task_is_still_queued(self) -> None:
        self.host_config()
        first = self.simple_task()
        second = self.simple_task(task_id="second", target="src/second.txt")
        self.write_tasks(first, second)
        job = jobs.start(self.root)
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "note.txt").write_text("done", encoding="utf-8")
        jobs.complete_task(self.root, "write-note", job_id=job["job_id"])
        payload = jobs.status(self.root, job["job_id"])
        self.assertFalse(payload["done"])
        self.assertIsNone(payload["finished_at"])

    def test_finished_at_is_stamped_once_and_not_rewritten(self) -> None:
        self.host_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        jobs.complete_task(self.root, "write-note", job_id=job["job_id"])
        first = jobs.status(self.root, job["job_id"])["finished_at"]
        second = jobs.status(self.root, job["job_id"])["finished_at"]
        self.assertEqual(first, second)


# --------------------------------------------------------------- help text


class TestUsageMatchesDispatch(unittest.TestCase):
    """`jobs --help` and what `jobs.run` really handles must not drift apart.

    `shape` and `--force-retry` were once dispatched but absent from the help.
    """

    #: Read by `run` but deliberately not in the help: the help switch itself.
    UNLISTED_FLAGS = {"--help"}

    def _run_source(self) -> str:
        import inspect
        return inspect.getsource(jobs.run)

    def _flags_read(self) -> set:
        import re
        return set(re.findall(r'"(--[a-z-]+)"', self._run_source()))

    def _dispatched(self) -> set:
        import re
        src = self._run_source()
        names = set(re.findall(r'cmd == "([a-z-]+)"', src))
        for group in re.findall(r"cmd in \(([^)]*)\)", src):
            names.update(re.findall(r'"([a-z-]+)"', group))
        return names

    def test_every_dispatched_command_is_listed(self) -> None:
        dispatched = self._dispatched()
        self.assertIn("start", dispatched)    # the `==` scan still works
        self.assertIn("results", dispatched)  # and the `in (...)` scan
        self.assertEqual(dispatched, set(jobs.COMMAND_NAMES))

    def test_usage_prints_every_command_once(self) -> None:
        import re
        printed = re.findall(r"^  ([a-z-]+)", jobs._usage(), re.M)
        self.assertEqual(printed, list(jobs.COMMAND_NAMES))
        self.assertEqual(len(set(printed)), len(printed))

    def test_every_flag_run_reads_is_in_usage(self) -> None:
        flags = self._flags_read()
        self.assertIn("--force-retry", flags)  # the scan still works
        usage = jobs._usage()
        missing = sorted(f for f in flags - self.UNLISTED_FLAGS if f not in usage)
        self.assertEqual(missing, [])

    def test_usage_names_no_flag_run_does_not_read(self) -> None:
        import re
        # The first line starts with the launcher (`uv run --project ... --frozen ...`): its
        # flags belong to uv, not to `jobs`.
        usage = jobs._usage().replace(jobs.paths.cli_invocation(), "")
        listed = set(re.findall(r"--[a-z-]+", usage))
        self.assertEqual(sorted(listed - self._flags_read()), [])

    def test_help_and_unknown_command_exit_codes(self) -> None:
        import contextlib
        import io
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(jobs.run(["--help"]), 0)
            self.assertEqual(jobs.run([]), 1)
        self.assertEqual(out.getvalue(), jobs._usage() * 2)
        self.assertEqual(err.getvalue(), "")
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(jobs.run(["bogus"]), 2)
        self.assertEqual(err.getvalue(),
                         "jobs: unknown command 'bogus'\n\n" + jobs._usage())
