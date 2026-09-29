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
        self.assertEqual(cfg["worker"]["default"], "claude")
        self.assertTrue(cfg["worker"]["backends"]["claude"]["enabled"])
        self.assertEqual(cfg["build"]["max_retries"], 2)
        self.assertEqual(cfg["build"]["parallel"], 3)
        self.assertEqual(cfg["build"]["task_timeout_s"], 900)
        self.assertEqual(cfg["questions"]["interview_max_calls"], 2)
        self.assertEqual(cfg["questions"]["items_per_call"], 4)

    def test_load_does_not_mutate_module_defaults(self) -> None:
        cfg = config.load(self.root)
        cfg["worker"]["backends"]["claude"]["enabled"] = False
        cfg["build"]["max_retries"] = 99
        fresh = config.load(self.root)
        self.assertTrue(fresh["worker"]["backends"]["claude"]["enabled"])
        self.assertEqual(fresh["build"]["max_retries"], 2)
        self.assertEqual(config.DEFAULTS["build"]["max_retries"], 2)

    def test_defaults_never_disable_sandbox(self) -> None:
        for backend in config.DEFAULTS["worker"]["backends"].values():
            self.assertFalse(backend.get("unsafe", False))


class TestDeepMerge(TempProject):
    def test_partial_override_keeps_sibling_defaults(self) -> None:
        self.write_config({"build": {"parallel": 8}})
        cfg = config.load(self.root)
        self.assertEqual(cfg["build"]["parallel"], 8)
        self.assertEqual(cfg["build"]["max_retries"], 2)
        self.assertEqual(cfg["worker"]["default"], "claude")

    def test_nested_backend_override(self) -> None:
        self.write_config(
            {"worker": {"backends": {"claude": {"enabled": False}}}}
        )
        cfg = config.load(self.root)
        self.assertFalse(cfg["worker"]["backends"]["claude"]["enabled"])
        # argv default survives the partial override
        self.assertEqual(
            cfg["worker"]["backends"]["claude"]["argv"],
            config.DEFAULTS["worker"]["backends"]["claude"]["argv"],
        )

    def test_user_backend_is_added(self) -> None:
        self.write_config(
            {"worker": {"backends": {"mine": {"argv": ["mytool"], "enabled": True}}}}
        )
        cfg = config.load(self.root)
        self.assertEqual(cfg["worker"]["backends"]["mine"]["argv"], ["mytool"])
        self.assertIn("claude", cfg["worker"]["backends"])

    def test_list_is_replaced_not_merged(self) -> None:
        self.write_config({"worker": {"backends": {"claude": {"argv": ["x"]}}}})
        cfg = config.load(self.root)
        self.assertEqual(cfg["worker"]["backends"]["claude"]["argv"], ["x"])

    def test_enforce_flag_can_be_turned_off(self) -> None:
        self.write_config({"enforce_spec_before_code": False})
        self.assertFalse(config.load(self.root)["enforce_spec_before_code"])


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
        cfg["build"]["parallel"] = 5
        config.save(self.root, cfg)
        target = self.root / ".gatekit" / "config.json"
        self.assertTrue(target.is_file())
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["build"]["parallel"], 5)
        self.assertEqual(config.load(self.root)["build"]["parallel"], 5)

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
