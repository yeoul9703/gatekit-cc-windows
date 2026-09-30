"""util: the one place gatekit reads JSON, writes files atomically and stamps job times."""
from __future__ import annotations

import json
import pathlib
import re
import tempfile
import unittest

from gatekit import config, jobs, paths, util


class TestOneDefinition(unittest.TestCase):
    def test_old_names_point_at_util(self) -> None:
        self.assertIs(paths.replace_file, util.replace_file)
        self.assertIs(config.write_json_atomic, util.write_json_atomic)
        self.assertIs(config.write_text_atomic, util.write_text_atomic)
        self.assertIs(jobs.write_json, util.write_json_atomic)
        self.assertIs(jobs.read_json, util.read_json)
        self.assertIs(jobs._now, util.now_iso)


class TestReadJson(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)

    def test_missing_and_broken_files_give_the_default(self) -> None:
        self.assertEqual(util.read_json(self.root / "missing.json", {"d": 1}), {"d": 1})
        broken = self.root / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        self.assertIsNone(util.read_json(broken))

    def test_reads_what_the_file_holds(self) -> None:
        target = self.root / "list.json"
        target.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(util.read_json(target, {}), [1, 2])


class TestWriteJsonAtomic(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = pathlib.Path(self._tmp.name)

    def test_creates_parents_writes_utf8_and_leaves_nothing_else(self) -> None:
        target = self.root / "a" / "b" / "state.json"
        util.write_json_atomic(target, {"이름": "값"})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"이름": "값"})
        self.assertTrue(target.read_text(encoding="utf-8").endswith("\n"))
        self.assertEqual([p.name for p in target.parent.iterdir()], ["state.json"])

    def test_unserializable_data_touches_nothing(self) -> None:
        target = self.root / "new" / "state.json"
        with self.assertRaises(TypeError):
            util.write_json_atomic(target, {"bad": object()})
        self.assertFalse((self.root / "new").exists())


class TestNowIso(unittest.TestCase):
    def test_format(self) -> None:
        self.assertRegex(util.now_iso(), re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"))


if __name__ == "__main__":
    unittest.main()
