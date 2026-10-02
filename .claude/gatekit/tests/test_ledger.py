"""Tests for gatekit.ledger — per-session state, atomic writes, scope conflicts."""
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

from gatekit import ledger


class TempProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def ledger_path(self, session_id: str) -> pathlib.Path:
        return self.root / ".gatekit" / "runs" / f"{session_id}.json"


class TestLoadAndSave(TempProject):
    def test_creates_ledger_when_missing(self) -> None:
        led = ledger.Ledger.load(self.root, "sess-1")
        self.assertEqual(led.data["version"], 1)
        self.assertEqual(led.data["session_id"], "sess-1")
        self.assertEqual(led.data["output_lang"], "en")
        self.assertIsNone(led.data["active_pipeline"])
        self.assertEqual(led.data["questions"]["asked"], 0)
        self.assertEqual(led.data["questions"]["max_calls"], 2)
        self.assertFalse(led.data["questions"]["budget_exceeded"])
        self.assertEqual(led.data["scopes"], [])
        self.assertEqual(led.data["stop"]["block_count"], 0)
        self.assertIsNone(led.data["stop"]["final_verdict"])
        self.assertEqual(led.data["events"], [])

    def test_load_does_not_write_until_save(self) -> None:
        ledger.Ledger.load(self.root, "sess-1")
        self.assertFalse(self.ledger_path("sess-1").exists())

    def test_save_then_load_roundtrips(self) -> None:
        led = ledger.Ledger.load(self.root, "sess-1")
        led.data["output_lang"] = "ko"
        led.data["active_pipeline"] = "build"
        led.save()
        again = ledger.Ledger.load(self.root, "sess-1")
        self.assertEqual(again.data["output_lang"], "ko")
        self.assertEqual(again.data["active_pipeline"], "build")

    def test_save_updates_timestamp(self) -> None:
        led = ledger.Ledger.load(self.root, "sess-1")
        led.data["updated_at"] = "1999-01-01T00:00:00+00:00"
        led.save()
        stored = json.loads(self.ledger_path("sess-1").read_text(encoding="utf-8"))
        self.assertNotEqual(stored["updated_at"], "1999-01-01T00:00:00+00:00")

    def test_save_leaves_no_temp_files(self) -> None:
        ledger.Ledger.load(self.root, "sess-1").save()
        runs = self.root / ".gatekit" / "runs"
        self.assertEqual([p.name for p in runs.iterdir()], ["sess-1.json"])

    def test_strict_session_resolution_no_recent_file_fallback(self) -> None:
        first = ledger.Ledger.load(self.root, "sess-1")
        first.data["output_lang"] = "ko"
        first.data["active_pipeline"] = "verify"
        first.save()
        # A different session must get a fresh ledger, never sess-1's content.
        second = ledger.Ledger.load(self.root, "sess-2")
        self.assertEqual(second.data["session_id"], "sess-2")
        self.assertEqual(second.data["output_lang"], "en")
        self.assertIsNone(second.data["active_pipeline"])

    def test_corrupt_ledger_is_replaced_not_raised(self) -> None:
        target = self.ledger_path("sess-1")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{ this is not json", encoding="utf-8")
        led = ledger.Ledger.load(self.root, "sess-1")
        self.assertEqual(led.data["session_id"], "sess-1")
        self.assertEqual(led.data["events"], [])

    def test_non_object_ledger_is_replaced(self) -> None:
        target = self.ledger_path("sess-1")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("[1,2,3]", encoding="utf-8")
        self.assertEqual(ledger.Ledger.load(self.root, "sess-1").data["version"], 1)

    def test_missing_keys_are_backfilled(self) -> None:
        target = self.ledger_path("sess-1")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"version": 1, "session_id": "sess-1"}), encoding="utf-8")
        led = ledger.Ledger.load(self.root, "sess-1")
        self.assertEqual(led.data["scopes"], [])
        self.assertEqual(led.data["stop"]["block_count"], 0)
        self.assertEqual(led.data["questions"]["asked"], 0)

    def test_unsafe_session_id_cannot_escape_runs_dir(self) -> None:
        led = ledger.Ledger.load(self.root, "../../etc/passwd")
        led.save()
        runs = self.root / ".gatekit" / "runs"
        written = list(runs.glob("*.json"))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].parent, runs)


class TestEvents(TempProject):
    def test_append_event_records_kind_and_detail(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.append_event("write_denied", {"path": "src/x.ts"})
        self.assertEqual(len(led.data["events"]), 1)
        event = led.data["events"][0]
        self.assertEqual(event["kind"], "write_denied")
        self.assertEqual(event["detail"], {"path": "src/x.ts"})
        self.assertIn("ts", event)

    def test_append_event_default_detail_is_empty_dict(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.append_event("ping")
        self.assertEqual(led.data["events"][0]["detail"], {})

    def test_events_capped_at_500_dropping_oldest(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        for i in range(600):
            led.append_event("tick", {"i": i})
        self.assertEqual(len(led.data["events"]), 500)
        self.assertEqual(led.data["events"][0]["detail"]["i"], 100)
        self.assertEqual(led.data["events"][-1]["detail"]["i"], 599)

    def test_cap_constant_is_500(self) -> None:
        self.assertEqual(ledger.MAX_EVENTS, 500)


class TestScopes(TempProject):
    def test_add_scope_records_owner_and_time(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["src/auth/**"])
        entry = led.data["scopes"][0]
        self.assertEqual(entry["owner"], "agent-a")
        self.assertEqual(entry["write_scope"], ["src/auth/**"])
        self.assertIn("declared_at", entry)

    def test_add_scope_accepts_read_only_string(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", "read-only")
        self.assertEqual(led.data["scopes"][0]["write_scope"], "read-only")

    def test_read_only_never_conflicts(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["src/auth/**"])
        self.assertEqual(led.scope_conflicts("read-only"), [])

    def test_read_only_holder_is_not_a_conflict_target(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("reader", "read-only")
        self.assertEqual(led.scope_conflicts(["src/auth/**"]), [])

    def test_identical_globs_conflict(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["src/auth/**"])
        conflicts = led.scope_conflicts(["src/auth/**"])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["owner"], "agent-a")

    def test_disjoint_globs_do_not_conflict(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["src/auth/**"])
        self.assertEqual(led.scope_conflicts(["src/billing/**"]), [])

    def test_literal_inside_glob_directory_conflicts(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["src/auth/**"])
        self.assertEqual(len(led.scope_conflicts(["src/auth/token.ts"])), 1)

    def test_glob_containing_existing_literal_conflicts(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["src/auth/token.ts"])
        self.assertEqual(len(led.scope_conflicts(["src/auth/**"])), 1)

    def test_star_suffix_glob_matches_literal(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["src/auth/*.ts"])
        self.assertEqual(len(led.scope_conflicts(["src/auth/token.ts"])), 1)

    def test_distinct_literals_do_not_conflict(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["src/auth/token.ts"])
        self.assertEqual(led.scope_conflicts(["src/auth/session.ts"]), [])

    def test_broad_glob_conflicts_with_everything(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["**"])
        self.assertEqual(len(led.scope_conflicts(["src/anything/deep/file.ts"])), 1)

    def test_multiple_conflicting_owners_all_returned(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["src/auth/**"])
        led.add_scope("agent-b", ["src/**"])
        conflicts = led.scope_conflicts(["src/auth/token.ts"])
        self.assertEqual({c["owner"] for c in conflicts}, {"agent-a", "agent-b"})

    def test_path_normalization_leading_dot_slash(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["./src/auth/**"])
        self.assertEqual(len(led.scope_conflicts(["src/auth/token.ts"])), 1)

    def test_empty_scope_list_never_conflicts(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["src/**"])
        self.assertEqual(led.scope_conflicts([]), [])

    def test_conflicts_survive_save_and_reload(self) -> None:
        led = ledger.Ledger.load(self.root, "s")
        led.add_scope("agent-a", ["src/auth/**"])
        led.save()
        again = ledger.Ledger.load(self.root, "s")
        self.assertEqual(len(again.scope_conflicts(["src/auth/token.ts"])), 1)


class TestReleaseScopes(TempProject):
    def test_release_by_owner_keeps_the_others(self) -> None:
        led = ledger.Ledger.load(self.root, "s1")
        led.add_scope("a", ["src/a/**"])
        led.add_scope("b", ["src/b/**"])
        self.assertEqual(led.release_scopes("a"), 1)
        self.assertEqual([s["owner"] for s in led.data["scopes"]], ["b"])
        self.assertEqual(led.scope_conflicts(["src/a/x.py"]), [])
        self.assertEqual(led.data["events"][-1]["kind"], "scopes_released")

    def test_release_all_and_releasing_nothing(self) -> None:
        led = ledger.Ledger.load(self.root, "s1")
        led.add_scope("a", ["src/a/**"])
        led.add_scope("b", "read-only")
        self.assertEqual(led.release_scopes(), 2)
        self.assertEqual(led.data["scopes"], [])
        events = len(led.data["events"])
        self.assertEqual(led.release_scopes(), 0)
        self.assertEqual(len(led.data["events"]), events)  # nothing released, nothing logged

    def test_cli_release_scopes(self) -> None:
        led = ledger.Ledger.load(self.root, "s1")
        led.add_scope("a", ["src/a/**"])
        led.add_scope("b", ["src/b/**"])
        led.save()
        base = ["--root", str(self.root), "--session", "s1"]
        self.assertEqual(ledger.run(["release-scopes", "a"] + base), 0)
        self.assertEqual(len(ledger.Ledger.load(self.root, "s1").data["scopes"]), 1)
        self.assertEqual(ledger.run(["release-scopes"] + base), 0)
        self.assertEqual(ledger.Ledger.load(self.root, "s1").data["scopes"], [])
        self.assertEqual(ledger.run(["release-scopes", "--root", str(self.root), "--session", "nope"]), 1)


class TestScopesIntersect(unittest.TestCase):
    """The documented pairwise heuristic, exercised directly."""

    def test_symmetry(self) -> None:
        pairs = [
            ("src/auth/**", "src/auth/token.ts"),
            ("src/**", "src/auth/**"),
            ("a/*.ts", "a/b.ts"),
        ]
        for left, right in pairs:
            self.assertTrue(ledger.globs_intersect(left, right), (left, right))
            self.assertTrue(ledger.globs_intersect(right, left), (right, left))

    def test_disjoint_symmetry(self) -> None:
        self.assertFalse(ledger.globs_intersect("a/**", "b/**"))
        self.assertFalse(ledger.globs_intersect("b/**", "a/**"))

    def test_identical(self) -> None:
        self.assertTrue(ledger.globs_intersect("x/y/**", "x/y/**"))


class TestRun(TempProject):
    def _run(self, argv: "list[str]") -> "tuple[int, str]":
        import io
        from contextlib import redirect_stderr, redirect_stdout

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = ledger.run(argv)
        return rc, out.getvalue()

    def test_show_missing_session_reports_and_exits_nonzero(self) -> None:
        rc, _ = self._run(["show", "--root", str(self.root), "--session", "nope"])
        self.assertEqual(rc, 1)

    def test_init_then_show(self) -> None:
        rc, _ = self._run(["init", "--root", str(self.root), "--session", "s1"])
        self.assertEqual(rc, 0)
        self.assertTrue(self.ledger_path("s1").exists())
        rc, out = self._run(["show", "--root", str(self.root), "--session", "s1"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["session_id"], "s1")

    def test_unknown_subcommand_is_nonzero(self) -> None:
        rc, _ = self._run(["bogus", "--root", str(self.root)])
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestSetPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pipelines_constant_matches_architecture(self) -> None:
        self.assertEqual(
            ledger.PIPELINES,
            ("discover", "interview", "mockup", "design", "tasks", "gate", "build", "verify"),
        )

    def test_set_pipeline_persists(self) -> None:
        led = ledger.Ledger.load(self.root, "s1")
        self.assertTrue(led.set_pipeline("build"))
        led.save()
        self.assertEqual(ledger.Ledger.load(self.root, "s1").data["active_pipeline"], "build")

    def test_set_pipeline_none_clears(self) -> None:
        led = ledger.Ledger.load(self.root, "s1")
        led.set_pipeline("build")
        self.assertTrue(led.set_pipeline(None))
        self.assertIsNone(led.data["active_pipeline"])

    def test_set_pipeline_rejects_unknown(self) -> None:
        led = ledger.Ledger.load(self.root, "s1")
        led.set_pipeline("build")
        self.assertFalse(led.set_pipeline("deploy"))
        self.assertEqual(led.data["active_pipeline"], "build")

    def test_cli_set_pipeline(self) -> None:
        code = ledger.run(["set-pipeline", "verify", "--root", str(self.root), "--session", "s2"])
        self.assertEqual(code, 0)
        self.assertEqual(ledger.Ledger.load(self.root, "s2").data["active_pipeline"], "verify")

    def test_cli_set_pipeline_none(self) -> None:
        ledger.run(["set-pipeline", "verify", "--root", str(self.root), "--session", "s2"])
        code = ledger.run(["set-pipeline", "none", "--root", str(self.root), "--session", "s2"])
        self.assertEqual(code, 0)
        self.assertIsNone(ledger.Ledger.load(self.root, "s2").data["active_pipeline"])

    def test_cli_set_pipeline_unknown_is_nonzero(self) -> None:
        code = ledger.run(["set-pipeline", "deploy", "--root", str(self.root), "--session", "s2"])
        self.assertNotEqual(code, 0)


class TestDesignPipeline(unittest.TestCase):
    """ADR-0008: `design` is a pipeline a session can enter at any stage."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_design_sits_between_mockup_and_tasks(self) -> None:
        self.assertEqual(
            ledger.PIPELINES,
            ("discover", "interview", "mockup", "design", "tasks", "gate", "build", "verify"),
        )

    def test_design_can_be_set_as_the_active_pipeline(self) -> None:
        led = ledger.Ledger.load(self.root, "s-design")
        self.assertTrue(led.set_pipeline("design"))
        led.save()
        self.assertEqual(
            ledger.Ledger.load(self.root, "s-design").data["active_pipeline"], "design"
        )
