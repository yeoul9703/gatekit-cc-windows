"""Tests for gatekit.hosts — generate a Codex host layer from the plugin."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

PLUGIN_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from gatekit import hosts  # noqa: E402


class HostProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def install(self, **kw) -> dict:
        return hosts.install(self.root, "codex", plugin_root=PLUGIN_DIR, **kw)


class TestCodexInstall(HostProject):
    def test_writes_hooks_json_for_every_gate(self) -> None:
        self.install()
        data = json.loads((self.root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        events = data["hooks"]
        self.assertIn("UserPromptSubmit", events)
        self.assertIn("PreToolUse", events)
        self.assertIn("PostToolUse", events)
        self.assertIn("Stop", events)
        commands = [h["command"] for group in events.values() for entry in group for h in entry["hooks"]]
        for gate in ("prompt.py", "write.py", "bash.py", "spawn.py", "question.py", "stop.py"):
            self.assertTrue(any(gate in c for c in commands), gate)
        self.assertTrue(all("--host codex" in c for c in commands))

    def test_write_matcher_includes_apply_patch(self) -> None:
        self.install()
        data = json.loads((self.root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        matchers = [entry["matcher"] for entry in data["hooks"]["PreToolUse"]]
        self.assertTrue(any("apply_patch" in m and "Write" in m for m in matchers))
        self.assertIn("Bash", matchers)

    def test_hook_commands_point_at_existing_gate_scripts(self) -> None:
        self.install()
        data = json.loads((self.root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        for group in data["hooks"].values():
            for entry in group:
                for h in entry["hooks"]:
                    script = h["command"].split('"')[1]
                    self.assertTrue(pathlib.Path(script).is_file(), script)

    def test_stop_timeout_matches_claude_hooks(self) -> None:
        self.install()
        data = json.loads((self.root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        claude = json.loads((PLUGIN_DIR / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(
            data["hooks"]["Stop"][0]["hooks"][0]["timeout"],
            claude["hooks"]["Stop"][0]["hooks"][0]["timeout"],
        )

    def test_writes_one_skill_per_command(self) -> None:
        self.install()
        skills = self.root / ".agents" / "skills"
        commands = {p.stem for p in (PLUGIN_DIR / "commands").glob("*.md")}
        self.assertEqual({p.name for p in skills.iterdir()}, {"gatekit-" + c for c in commands})
        for name in commands:
            self.assertTrue((skills / ("gatekit-" + name) / "SKILL.md").is_file())
            self.assertTrue((skills / ("gatekit-" + name) / "command.md").is_file())

    def test_skill_shim_is_short_and_points_at_command(self) -> None:
        self.install()
        text = (self.root / ".agents" / "skills" / "gatekit-build" / "SKILL.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 40)
        self.assertIn("command.md", text)
        self.assertTrue(text.startswith("---\nname: gatekit-build\n"))
        self.assertIn("description:", text)

    def test_command_copy_is_rewritten_for_codex(self) -> None:
        self.install()
        text = (self.root / ".agents" / "skills" / "gatekit-build" / "command.md").read_text(encoding="utf-8")
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", text)
        self.assertIn(str(PLUGIN_DIR / "bin" / "gatekit.py"), text)
        self.assertNotIn("/gatekit:verify", text)
        self.assertIn("$gatekit-verify", text)

    def test_command_copy_keeps_original_body(self) -> None:
        self.install()
        original = (PLUGIN_DIR / "commands" / "tasks.md").read_text(encoding="utf-8")
        copy = (self.root / ".agents" / "skills" / "gatekit-tasks" / "command.md").read_text(encoding="utf-8")
        self.assertIn("## Step 1", original)
        self.assertIn("## Step 1", copy)

    def test_agents_md_created_with_managed_block(self) -> None:
        self.install()
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(hosts.BLOCK_BEGIN, text)
        self.assertIn(hosts.BLOCK_END, text)
        self.assertIn("spec validate", text)
        self.assertIn("AskUserQuestion", text)

    def test_existing_agents_md_is_preserved_around_block(self) -> None:
        (self.root / "AGENTS.md").write_text("# mine\n\nkeep this\n", encoding="utf-8")
        self.install()
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# mine\n\nkeep this\n"))
        self.assertIn(hosts.BLOCK_BEGIN, text)

    def test_reinstall_replaces_block_not_duplicates(self) -> None:
        self.install()
        self.install()
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertEqual(text.count(hosts.BLOCK_BEGIN), 1)

    def test_returns_written_paths(self) -> None:
        result = self.install()
        rels = {str(p) for p in result["written"]}
        self.assertIn(".codex/hooks.json", rels)
        self.assertIn("AGENTS.md", rels)
        self.assertTrue(any(r.startswith(".agents/skills/gatekit-") for r in rels))

    def test_dry_run_writes_nothing(self) -> None:
        result = self.install(dry_run=True)
        self.assertFalse((self.root / ".codex").exists())
        self.assertTrue(result["written"])

    def test_unknown_host_rejected(self) -> None:
        with self.assertRaises(ValueError):
            hosts.install(self.root, "vim", plugin_root=PLUGIN_DIR)

    def test_claude_host_is_not_installable_this_way(self) -> None:
        with self.assertRaises(ValueError):
            hosts.install(self.root, "claude", plugin_root=PLUGIN_DIR)


class TestCodexStatus(HostProject):
    def test_status_absent(self) -> None:
        self.assertEqual(hosts.status(self.root, "codex", plugin_root=PLUGIN_DIR)["verdict"], "unverified")

    def test_status_ok_after_install(self) -> None:
        self.install()
        self.assertEqual(hosts.status(self.root, "codex", plugin_root=PLUGIN_DIR)["verdict"], "ok")

    def test_status_fail_when_gate_script_missing(self) -> None:
        self.install()
        path = self.root / ".codex" / "hooks.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["hooks"]["Stop"][0]["hooks"][0]["command"] = 'python3 "/nowhere/stop.py" --host codex'
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(hosts.status(self.root, "codex", plugin_root=PLUGIN_DIR)["verdict"], "fail")

    def test_status_fail_when_json_broken(self) -> None:
        self.install()
        (self.root / ".codex" / "hooks.json").write_text("{", encoding="utf-8")
        self.assertEqual(hosts.status(self.root, "codex", plugin_root=PLUGIN_DIR)["verdict"], "fail")


class TestCli(HostProject):
    def test_install_subcommand(self) -> None:
        code = hosts.run(["--host", "codex", "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / ".codex" / "hooks.json").is_file())

    def test_missing_host_is_usage_error(self) -> None:
        self.assertNotEqual(hosts.run(["--root", str(self.root)]), 0)


class TestDoctorAxis(HostProject):
    def test_doctor_has_host_axis(self) -> None:
        from gatekit import doctor

        names = [fn.__name__ for fn in doctor.AXES]
        self.assertIn("axis_host_layer", names)
        self.assertEqual(len(doctor.AXES), 8)

    def test_axis_ok_when_absent(self) -> None:
        from gatekit import doctor

        self.assertEqual(doctor.axis_host_layer(self.root)["verdict"], "ok")

    def test_axis_fail_when_broken(self) -> None:
        from gatekit import doctor

        self.install()
        (self.root / ".codex" / "hooks.json").write_text("{", encoding="utf-8")
        self.assertEqual(doctor.axis_host_layer(self.root)["verdict"], "fail")


if __name__ == "__main__":
    unittest.main()


class TestInstallSafety(HostProject):
    def test_symlinked_dir_outside_root_is_refused(self) -> None:
        import shutil
        outside = pathlib.Path(tempfile.mkdtemp())
        try:
            os.symlink(str(outside), str(self.root / ".agents"))
            with self.assertRaises(ValueError):
                self.install()
            self.assertFalse(list(outside.iterdir()))
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_reversed_markers_do_not_swallow_user_text(self) -> None:
        (self.root / "AGENTS.md").write_text(
            "keep A\n" + hosts.BLOCK_END + "\nkeep B\n" + hosts.BLOCK_BEGIN + "\nkeep C\n", encoding="utf-8"
        )
        self.install()
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        for part in ("keep A", "keep B", "keep C"):
            self.assertIn(part, text)
        self.assertEqual(text.count(hosts.BLOCK_BEGIN), 2)

    def test_rewrite_keeps_urls_and_unknown_suffixes(self) -> None:
        text = "see https://example.com/gatekit:build and /gatekit:build-x and /gatekit:verify."
        out = hosts.rewrite_command(text, PLUGIN_DIR)
        self.assertIn("https://example.com/gatekit:build", out)
        self.assertIn("/gatekit:build-x", out)
        self.assertIn("$gatekit-verify.", out)

    def test_workers_list_json_reports_evaluator(self) -> None:
        import io
        from contextlib import redirect_stdout
        from gatekit import workers

        buf = io.StringIO()
        with redirect_stdout(buf):
            workers.run(["list", "--json", "--root", str(self.root)])
        self.assertEqual(json.loads(buf.getvalue())["evaluator"], "agent")


# ------------------------------------------- ADR-0015: codex hook trust


class CodexTrustProject(HostProject):
    """A fake $CODEX_HOME so these tests never touch the real ~/.codex."""

    def setUp(self) -> None:
        super().setUp()
        self._codex_home = tempfile.TemporaryDirectory()
        self.codex_home = pathlib.Path(os.path.realpath(self._codex_home.name))
        self._env_patch = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = str(self.codex_home)

    def tearDown(self) -> None:
        if self._env_patch is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = self._env_patch
        self._codex_home.cleanup()
        super().tearDown()

    def write_config(self, text: str) -> None:
        (self.codex_home / "config.toml").write_text(text, encoding="utf-8")

    def hooks_json_path(self) -> str:
        return str((self.root / ".codex" / "hooks.json").resolve())


class TestCodexHooksTrusted(CodexTrustProject):
    def test_no_config_file_is_not_trusted(self) -> None:
        self.install()
        self.assertFalse(hosts.codex_hooks_trusted(self.root))

    def test_config_with_no_matching_entry_is_not_trusted(self) -> None:
        self.install()
        self.write_config(
            '[hooks.state."/some/other/project/.codex/hooks.json:pre_tool_use:0:0"]\n'
            'trusted_hash = "sha256:deadbeef"\n'
        )
        self.assertFalse(hosts.codex_hooks_trusted(self.root))

    def test_a_matching_pre_tool_use_entry_is_trusted(self) -> None:
        self.install()
        self.write_config(
            '[hooks.state."%s:pre_tool_use:0:0"]\n'
            'trusted_hash = "sha256:deadbeef"\n' % self.hooks_json_path()
        )
        self.assertTrue(hosts.codex_hooks_trusted(self.root))

    def test_a_matching_entry_for_a_different_event_still_counts(self) -> None:
        """Any trusted hook from this project's hooks.json is a signal that
        the layer was approved; the write gate specifically is what matters
        most, but user_prompt_submit trust implies the same approval flow
        was completed for this file."""
        self.install()
        self.write_config(
            '[hooks.state."%s:pre_tool_use:1:0"]\n'
            'trusted_hash = "sha256:deadbeef"\n' % self.hooks_json_path()
        )
        self.assertTrue(hosts.codex_hooks_trusted(self.root))

    def test_project_trust_alone_is_not_hook_trust(self) -> None:
        """The real gk-trial2 case: `trust_level = "trusted"` at the project
        level with zero hooks.state entries. Project trust and hook trust are
        recorded separately, and only the second gates a hook actually firing."""
        self.install()
        self.write_config(
            '[projects."%s"]\n'
            'trust_level = "trusted"\n' % str(self.root.resolve())
        )
        self.assertFalse(hosts.codex_hooks_trusted(self.root))

    def test_malformed_toml_reads_as_not_trusted(self) -> None:
        self.install()
        self.write_config("[[[not valid toml")
        self.assertFalse(hosts.codex_hooks_trusted(self.root))

    def test_no_codex_directory_at_all_is_not_trusted(self) -> None:
        # No install() call: .codex/hooks.json does not exist yet.
        self.write_config(
            '[hooks.state."%s:pre_tool_use:0:0"]\n'
            'trusted_hash = "sha256:deadbeef"\n' % self.hooks_json_path()
        )
        self.assertFalse(hosts.codex_hooks_trusted(self.root))

    def test_empty_hooks_state_table_is_not_trusted(self) -> None:
        self.install()
        self.write_config("[hooks.state]\n")
        self.assertFalse(hosts.codex_hooks_trusted(self.root))


class TestCodexTrustFallbackParser(CodexTrustProject):
    """Force the pre-3.11 code path even when tomllib is available here, so
    the fallback is actually exercised rather than merely present."""

    def with_fallback(self, fn):
        original = hosts.tomllib
        hosts.tomllib = None
        try:
            return fn()
        finally:
            hosts.tomllib = original

    def test_fallback_matches_a_trusted_hook(self) -> None:
        self.install()
        self.write_config(
            '[hooks.state."%s:pre_tool_use:0:0"]\n'
            'trusted_hash = "sha256:deadbeef"\n' % self.hooks_json_path()
        )
        self.assertTrue(self.with_fallback(lambda: hosts.codex_hooks_trusted(self.root)))

    def test_fallback_rejects_an_untrusted_project(self) -> None:
        self.install()
        self.write_config(
            '[projects."%s"]\n'
            'trust_level = "trusted"\n' % str(self.root.resolve())
        )
        self.assertFalse(self.with_fallback(lambda: hosts.codex_hooks_trusted(self.root)))

    def test_fallback_handles_escaped_quotes_in_the_key(self) -> None:
        # A defensive case: Codex's own keys are plain paths today, but the
        # header syntax allows escaped quotes and the parser must not choke.
        text = _trusted_hook_keys_source = (
            '[hooks.state."/weird\\"path/.codex/hooks.json:pre_tool_use:0:0"]\n'
            'trusted_hash = "sha256:deadbeef"\n'
        )
        keys = self.with_fallback(lambda: hosts._trusted_hook_keys(text))
        self.assertEqual(keys, ['/weird"path/.codex/hooks.json:pre_tool_use:0:0'])
