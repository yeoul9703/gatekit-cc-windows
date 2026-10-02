"""Tests for gatekit.design — tokens.json v2 loading, preset merge, impact.

ADR-0008: design enters as data at any stage; a changed design makes the
contract stale. This module covers the design kernel: the normalizing loader,
the `design merge-preset` CLI, and the `design impact` blast-radius report.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import design, paths


class TempProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_tokens(self, data: dict) -> None:
        (self.root / "spec" / "tokens.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# ---------------------------------------------------------------- load_tokens


class TestLoadTokens(TempProject):
    def test_absent_file_is_empty_dict(self) -> None:
        self.assertEqual(design.load_tokens(self.root), {})

    def test_unparsable_file_is_empty_dict(self) -> None:
        (self.root / "spec" / "tokens.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(design.load_tokens(self.root), {})

    def test_non_object_file_is_empty_dict(self) -> None:
        (self.root / "spec" / "tokens.json").write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(design.load_tokens(self.root), {})

    def test_v1_is_upgraded_in_memory(self) -> None:
        self.write_tokens(
            {
                "source": "figma.com/file/abc",
                "color": {"primary": "#3366ff"},
                "space": {"md": "16px"},
                "font": {"body": "16px/1.5"},
            }
        )
        data = design.load_tokens(self.root)
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["source"], ["figma.com/file/abc"])
        self.assertEqual(data["patterns"], [])
        self.assertEqual(data["color"], {"primary": "#3366ff"})

    def test_v1_without_source_gets_empty_source_list(self) -> None:
        self.write_tokens({"color": {"primary": "#000"}})
        data = design.load_tokens(self.root)
        self.assertEqual(data["source"], [])
        self.assertEqual(data["version"], 2)

    def test_v2_is_returned_as_is(self) -> None:
        raw = {
            "version": 2,
            "source": ["preset:calm", "spec/design/home.png"],
            "patterns": [
                {"id": "P1", "rule": "Cards in a list.", "applies_to": ["S1"], "evidence": "preset:calm"}
            ],
            "color": {"primary": {"value": "#3366ff", "evidence": "preset:calm"}},
        }
        self.write_tokens(raw)
        data = design.load_tokens(self.root)
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["source"], ["preset:calm", "spec/design/home.png"])
        self.assertEqual(data["patterns"][0]["id"], "P1")

    def test_groups_are_open(self) -> None:
        self.write_tokens({"version": 2, "source": [], "patterns": [], "radius": {"sm": "4px"}})
        self.assertEqual(design.token_groups(design.load_tokens(self.root)), {"radius": {"sm": "4px"}})

    def test_non_list_non_string_source_becomes_an_empty_list(self) -> None:
        self.write_tokens({"version": 2, "source": 7, "color": {"a": "#000"}})
        self.assertEqual(design.load_tokens(self.root)["source"], [])

    def test_reserved_keys_come_first_in_the_normalized_dict(self) -> None:
        self.write_tokens({"color": {"a": "#000"}, "source": "x"})
        self.assertEqual(
            list(design.load_tokens(self.root))[:3], ["version", "source", "patterns"]
        )

    def test_token_groups_skips_reserved_keys(self) -> None:
        data = {"version": 2, "source": ["x"], "patterns": [{"id": "P1"}], "color": {"a": "#000"}}
        self.assertEqual(list(design.token_groups(data)), ["color"])


# ------------------------------------------------------------- merge_preset


class PresetTestCase(TempProject):
    """A temp plugin root so tests never read or write the installed presets."""

    def setUp(self) -> None:
        super().setUp()
        self._plugin_tmp = tempfile.TemporaryDirectory()
        self.plugin = pathlib.Path(os.path.realpath(self._plugin_tmp.name))
        # The same shape as an install: <tmp>/.claude/gatekit beside <tmp>/.claude/skills.
        self.plugin = self.plugin / ".claude" / "gatekit"
        self.plugin.mkdir(parents=True)
        self.presets = (self.plugin.parent / "skills" / "gatekit-shared" / "assets"
                        / "presets" / "design")
        self.presets.mkdir(parents=True)
        self._orig_plugin_root = paths.gatekit_root
        paths.gatekit_root = lambda: self.plugin

    def tearDown(self) -> None:
        paths.gatekit_root = self._orig_plugin_root
        self._plugin_tmp.cleanup()
        super().tearDown()

    def write_preset(self, name: str, data: dict) -> None:
        (self.presets / (name + ".json")).write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

    def read_tokens(self) -> dict:
        return json.loads((self.root / "spec" / "tokens.json").read_text(encoding="utf-8"))


class TestMergePreset(PresetTestCase):
    def test_missing_preset_is_an_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            design.merge_preset(self.root, "nope")

    def test_unparsable_preset_is_an_error(self) -> None:
        (self.presets / "bad.json").write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            design.merge_preset(self.root, "bad")

    def test_preset_fills_gaps_into_an_absent_tokens_file(self) -> None:
        self.write_preset("calm", {"version": 2, "color": {"primary": "#123456"}})
        design.merge_preset(self.root, "calm")
        data = self.read_tokens()
        self.assertEqual(data["version"], 2)
        self.assertEqual(
            data["color"]["primary"], {"value": "#123456", "evidence": "preset:calm"}
        )

    def test_project_values_win_over_the_preset(self) -> None:
        self.write_tokens({"version": 2, "source": [], "patterns": [], "color": {"primary": "#aaaaaa"}})
        self.write_preset("calm", {"color": {"primary": "#123456", "accent": "#ff0000"}})
        design.merge_preset(self.root, "calm")
        data = self.read_tokens()
        self.assertEqual(data["color"]["primary"], "#aaaaaa")
        self.assertEqual(data["color"]["accent"], {"value": "#ff0000", "evidence": "preset:calm"})

    def test_scalar_token_added_by_preset_is_upgraded_to_an_object(self) -> None:
        self.write_preset("calm", {"space": {"md": "16px"}})
        design.merge_preset(self.root, "calm")
        self.assertEqual(
            self.read_tokens()["space"]["md"], {"value": "16px", "evidence": "preset:calm"}
        )

    def test_object_token_added_by_preset_keeps_its_own_evidence(self) -> None:
        self.write_preset(
            "calm", {"color": {"primary": {"value": "#123456", "evidence": "brand book"}}}
        )
        design.merge_preset(self.root, "calm")
        self.assertEqual(
            self.read_tokens()["color"]["primary"],
            {"value": "#123456", "evidence": "preset:calm"},
        )

    def test_patterns_are_added_with_preset_evidence(self) -> None:
        self.write_preset(
            "calm",
            {"patterns": [{"id": "P1", "rule": "Cards in a list.", "applies_to": "all"}]},
        )
        design.merge_preset(self.root, "calm")
        patterns = self.read_tokens()["patterns"]
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0]["evidence"], "preset:calm")
        self.assertEqual(patterns[0]["rule"], "Cards in a list.")

    def test_existing_pattern_id_is_not_overwritten(self) -> None:
        self.write_tokens(
            {
                "version": 2,
                "source": [],
                "patterns": [
                    {"id": "P1", "rule": "Mine.", "applies_to": "all", "evidence": "spec/design/a.png"}
                ],
            }
        )
        self.write_preset("calm", {"patterns": [{"id": "P1", "rule": "Theirs.", "applies_to": "all"}]})
        design.merge_preset(self.root, "calm")
        patterns = self.read_tokens()["patterns"]
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0]["rule"], "Mine.")

    def test_source_gains_the_preset_name_once(self) -> None:
        self.write_preset("calm", {"color": {"primary": "#123456"}})
        design.merge_preset(self.root, "calm")
        design.merge_preset(self.root, "calm")
        self.assertEqual(self.read_tokens()["source"].count("preset:calm"), 1)

    def test_v1_project_file_is_upgraded_on_merge(self) -> None:
        self.write_tokens({"source": "figma.com/x", "color": {"primary": "#aaaaaa"}})
        self.write_preset("calm", {"color": {"accent": "#123456"}})
        design.merge_preset(self.root, "calm")
        data = self.read_tokens()
        self.assertEqual(data["version"], 2)
        self.assertEqual(data["source"], ["figma.com/x", "preset:calm"])
        self.assertEqual(data["color"]["primary"], "#aaaaaa")

    def test_write_leaves_no_temp_files(self) -> None:
        self.write_preset("calm", {"color": {"primary": "#123456"}})
        design.merge_preset(self.root, "calm")
        leftovers = [p.name for p in (self.root / "spec").iterdir() if p.name.startswith(".")]
        self.assertEqual(leftovers, [])


class TestMergePresetCLI(PresetTestCase):
    def test_missing_preset_exits_non_zero_with_a_message(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = design.run(["merge-preset", "nope", "--root", str(self.root)])
        self.assertNotEqual(code, 0)
        self.assertIn("nope", err.getvalue())

    def test_merge_preset_writes_and_reports(self) -> None:
        self.write_preset("calm", {"color": {"primary": "#123456"}})
        out = io.StringIO()
        with redirect_stdout(out):
            code = design.run(["merge-preset", "calm", "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("calm", out.getvalue())
        self.assertTrue((self.root / "spec" / "tokens.json").is_file())


# ----------------------------------------------------------------- impact


TASK_FENCE = """```gatekit-task
%s
```
"""


class TestImpact(TempProject):
    def write_tasks(self, *tasks: dict) -> None:
        body = "# Tasks\n\n" + "".join(TASK_FENCE % json.dumps(t) for t in tasks)
        (self.root / "spec" / "04-tasks.md").write_text(body, encoding="utf-8")

    def test_no_tasks_file_is_an_empty_report(self) -> None:
        self.assertEqual(design.impact(self.root)["tasks"], [])

    def test_title_reference_is_found(self) -> None:
        self.write_tasks({"id": "t1", "title": "Build S1 list", "instruction": "do it"})
        report = design.impact(self.root)
        self.assertEqual(report["tasks"], [{"id": "t1", "refs": ["S1"]}])

    def test_instruction_reference_is_found(self) -> None:
        self.write_tasks({"id": "t1", "title": "x", "instruction": "Follow P2 exactly."})
        self.assertEqual(design.impact(self.root)["tasks"], [{"id": "t1", "refs": ["P2"]}])

    def test_gate_argv_reference_is_found(self) -> None:
        self.write_tasks(
            {"id": "t1", "title": "x", "instruction": "y",
             "gates": [{"name": "g", "argv": ["python3", "check.py", "--screen", "S3"]}]}
        )
        self.assertEqual(design.impact(self.root)["tasks"], [{"id": "t1", "refs": ["S3"]}])

    def test_refs_are_sorted_and_deduplicated(self) -> None:
        self.write_tasks({"id": "t1", "title": "S2 and S1", "instruction": "S1 again, plus P10 and P2"})
        self.assertEqual(
            design.impact(self.root)["tasks"], [{"id": "t1", "refs": ["P2", "P10", "S1", "S2"]}]
        )

    def test_task_without_references_is_omitted(self) -> None:
        self.write_tasks(
            {"id": "t1", "title": "S1", "instruction": "x"},
            {"id": "t2", "title": "nothing", "instruction": "plain"},
        )
        self.assertEqual([t["id"] for t in design.impact(self.root)["tasks"]], ["t1"])

    def test_word_boundary_is_respected(self) -> None:
        self.write_tasks({"id": "t1", "title": "SUBS1TUTE and PS12", "instruction": "no refs here"})
        self.assertEqual(design.impact(self.root)["tasks"], [])

    def test_zero_padded_ids_merge_with_their_unpadded_form(self) -> None:
        """`S01` and `S1` are the same screen, so they are the same key.

        Left as written they split the report in two, and since both sort to
        the same position the two halves landed in arbitrary order.
        """
        self.write_tasks(
            {"id": "t1", "title": "S01 list", "instruction": "x"},
            {"id": "t2", "title": "S1 detail", "instruction": "y"},
        )
        report = design.impact(self.root)
        self.assertEqual(report["by_id"], {"S1": ["t1", "t2"]})
        self.assertEqual(
            report["tasks"], [{"id": "t1", "refs": ["S1"]}, {"id": "t2", "refs": ["S1"]}]
        )

    def test_padded_and_unpadded_in_one_task_collapse_to_one_ref(self) -> None:
        self.write_tasks({"id": "t1", "title": "S01 and S1", "instruction": "and P007 and P7"})
        self.assertEqual(design.impact(self.root)["tasks"], [{"id": "t1", "refs": ["P7", "S1"]}])

    def test_referenced_ids_normalizes_padding(self) -> None:
        self.assertEqual(design.referenced_ids("S01 S1 P007 P7"), ["P7", "S1"])
        self.assertEqual(design.referenced_ids("S010"), ["S10"])
        self.assertEqual(design.referenced_ids("S0"), ["S0"])

    def test_normalized_ids_still_sort_numerically(self) -> None:
        self.assertEqual(design.referenced_ids("S10 S02 P0003 P20"), ["P3", "P20", "S2", "S10"])

    def test_by_id_grouping_is_available(self) -> None:
        self.write_tasks(
            {"id": "t1", "title": "S1", "instruction": "x"},
            {"id": "t2", "title": "S1 and P1", "instruction": "y"},
        )
        report = design.impact(self.root)
        self.assertEqual(report["by_id"]["S1"], ["t1", "t2"])
        self.assertEqual(report["by_id"]["P1"], ["t2"])

    def test_json_output_shape(self) -> None:
        self.write_tasks({"id": "t1", "title": "S1", "instruction": "x"})
        out = io.StringIO()
        with redirect_stdout(out):
            code = design.run(["impact", "--json", "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out.getvalue()), {"tasks": [{"id": "t1", "refs": ["S1"]}]}
        )

    def test_table_output_names_the_ids(self) -> None:
        self.write_tasks({"id": "t1", "title": "S1", "instruction": "x"})
        out = io.StringIO()
        with redirect_stdout(out):
            code = design.run(["impact", "--root", str(self.root)])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("S1", text)
        self.assertIn("t1", text)


class TestCLIRegistration(unittest.TestCase):
    def test_design_is_a_registered_subcommand(self) -> None:
        from gatekit import cli

        self.assertIn("design", cli.SUBCOMMANDS)
        self.assertEqual(cli.SUBCOMMANDS["design"][0], "gatekit.design")

    def test_no_subcommand_prints_usage_and_returns_non_zero(self) -> None:
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = design.run([])
        self.assertNotEqual(code, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
