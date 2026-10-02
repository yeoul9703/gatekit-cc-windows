"""Tests for gatekit.config — .gatekit/config.json loading with defaults."""
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

from gatekit import config


class TempProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_config(self, obj: object) -> None:
        (self.root / ".gatekit").mkdir(exist_ok=True)
        (self.root / ".gatekit" / "config.json").write_text(
            json.dumps(obj), encoding="utf-8"
        )


class TestDefaults(TempProject):
    def test_missing_file_returns_defaults(self) -> None:
        cfg = config.load(self.root)
        self.assertEqual(cfg["version"], 1)
        self.assertTrue(cfg["enforce_spec_before_code"])
        self.assertEqual(cfg["build"], {"max_retries": 2})
        self.assertEqual(cfg["questions"]["interview_max_calls"], 2)
        self.assertEqual(cfg["questions"]["items_per_call"], 4)

    def test_defaults_name_no_program_to_start(self) -> None:
        # Nothing starts a worker process or a reviewer program: no setting chooses one.
        for gone in ("worker", "verify"):
            self.assertNotIn(gone, config.DEFAULTS)
        for gone in ("execution", "parallel", "task_timeout_s"):
            self.assertNotIn(gone, config.DEFAULTS["build"])

    def test_load_does_not_mutate_module_defaults(self) -> None:
        cfg = config.load(self.root)
        cfg["questions"]["items_per_call"] = 99
        cfg["build"]["max_retries"] = 99
        fresh = config.load(self.root)
        self.assertEqual(fresh["questions"]["items_per_call"], 4)
        self.assertEqual(fresh["build"]["max_retries"], 2)
        self.assertEqual(config.DEFAULTS["build"]["max_retries"], 2)


class TestDeepMerge(TempProject):
    def test_partial_override_keeps_sibling_defaults(self) -> None:
        self.write_config({"questions": {"items_per_call": 3}})
        cfg = config.load(self.root)
        self.assertEqual(cfg["questions"]["items_per_call"], 3)
        self.assertEqual(cfg["questions"]["interview_max_calls"], 2)
        self.assertEqual(cfg["build"]["max_retries"], 2)

    def test_nested_override_merges_at_every_depth(self) -> None:
        base = {"a": {"b": {"keep": 1, "change": 1}, "sibling": True}}
        merged = config._deep_merge(base, {"a": {"b": {"change": 2}}})
        self.assertEqual(merged, {"a": {"b": {"keep": 1, "change": 2}, "sibling": True}})
        self.assertEqual(base["a"]["b"]["change"], 1)  # the base is not changed

    def test_a_key_the_defaults_do_not_know_is_kept(self) -> None:
        # Settings an older kit wrote are not an error: they pass through and nothing reads them.
        old = {"worker": {"default": "claude"}, "build": {"execution": "worker"},
               "verify": {"evaluator": "claude"}}
        self.write_config(old)
        cfg = config.load(self.root)
        self.assertEqual(cfg["worker"], {"default": "claude"})
        self.assertEqual(cfg["build"], {"max_retries": 2, "execution": "worker"})

    def test_list_is_replaced_not_merged(self) -> None:
        merged = config._deep_merge({"names": ["a", "b"]}, {"names": ["x"]})
        self.assertEqual(merged["names"], ["x"])

    def test_enforce_flag_can_be_turned_off(self) -> None:
        self.write_config({"enforce_spec_before_code": False})
        self.assertFalse(config.load(self.root)["enforce_spec_before_code"])

    def test_a_file_saved_with_a_bom_is_read(self) -> None:
        # Windows PowerShell 5.1 writes a BOM (Set-Content -Encoding UTF8). Read as plain
        # UTF-8 the file is not valid JSON, and the setting fell back to the default silently.
        (self.root / ".gatekit").mkdir()
        (self.root / ".gatekit" / "config.json").write_text(
            json.dumps({"build": {"max_retries": 5}}), encoding="utf-8-sig")
        self.assertTrue((self.root / ".gatekit" / "config.json").read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(config.load(self.root)["build"]["max_retries"], 5)


class TestCorruptInput(TempProject):
    def test_invalid_json_falls_back_to_defaults(self) -> None:
        (self.root / ".gatekit").mkdir()
        (self.root / ".gatekit" / "config.json").write_text("{not json", encoding="utf-8")
        cfg = config.load(self.root)
        self.assertEqual(cfg["build"]["max_retries"], 2)

    def test_non_object_json_falls_back_to_defaults(self) -> None:
        self.write_config([1, 2, 3])
        self.assertTrue(config.load(self.root)["enforce_spec_before_code"])


class TestSave(TempProject):
    def test_save_creates_dir_and_roundtrips(self) -> None:
        cfg = config.load(self.root)
        cfg["build"]["max_retries"] = 5
        config.save(self.root, cfg)
        target = self.root / ".gatekit" / "config.json"
        self.assertTrue(target.is_file())
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["build"]["max_retries"], 5)
        self.assertEqual(config.load(self.root)["build"]["max_retries"], 5)

    def test_save_leaves_no_tmp_files(self) -> None:
        config.save(self.root, config.load(self.root))
        leftovers = list((self.root / ".gatekit").glob("*.tmp*"))
        self.assertEqual(leftovers, [])

    def test_save_is_atomic_replace(self) -> None:
        config.save(self.root, {"version": 1, "marker": "first"})
        config.save(self.root, {"version": 1, "marker": "second"})
        data = json.loads((self.root / ".gatekit" / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(data["marker"], "second")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
