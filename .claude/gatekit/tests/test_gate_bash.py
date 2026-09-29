"""Tests for gates/bash.py — shell-level writes obey the same rules as Write."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import approval, ledger  # noqa: E402
from gatekit.gates import bash as bash_gate  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "bash.py"


def targets_of(command: str, cwd: str = ".") -> "tuple[list[str], bool]":
    result = bash_gate.extract_write_targets(command, cwd)
    return sorted(result.targets), result.opaque


class TestExtractRedirects(unittest.TestCase):
    def test_truncating_redirect(self) -> None:
        self.assertEqual(targets_of("cat > src/x.ts"), (["src/x.ts"], False))

    def test_appending_redirect(self) -> None:
        self.assertEqual(targets_of("echo hi >> notes.txt"), (["notes.txt"], False))

    def test_bare_truncation(self) -> None:
        self.assertEqual(targets_of("> x.ts"), (["x.ts"], False))

    def test_clobber_and_ampersand_forms(self) -> None:
        self.assertEqual(targets_of("cmd >| a; cmd &> b; cmd &>> c"), (["a", "b", "c"], False))

    def test_stderr_redirect_is_a_write(self) -> None:
        self.assertEqual(targets_of("cmd 2>errors.log"), (["errors.log"], False))

    def test_fd_dup_and_dev_null_are_not_writes(self) -> None:
        self.assertEqual(targets_of("ls > /dev/null 2>&1"), ([], False))

    def test_fd_number_is_not_mistaken_for_an_argument(self) -> None:
        self.assertEqual(targets_of("cp a b 2>err.log"), (["b", "err.log"], False))

    def test_process_substitution_is_opaque(self) -> None:
        self.assertTrue(targets_of("cat > >(gzip)")[1])

    def test_quoted_angle_bracket_is_not_a_redirect(self) -> None:
        self.assertEqual(targets_of('git commit -m "a > b"'), ([], False))

    def test_input_redirects_ignored(self) -> None:
        self.assertEqual(targets_of("sort < in.txt | head"), ([], False))

    def test_heredoc_body_is_not_parsed(self) -> None:
        cmd = "cat > x.ts <<'EOF'\nfoo > bar\ncd elsewhere\nEOF"
        self.assertEqual(targets_of(cmd), (["x.ts"], False))

    def test_heredoc_without_redirect_writes_nothing(self) -> None:
        self.assertEqual(targets_of("cat <<EOF\nhello > world\nEOF"), ([], False))


class TestExtractCommands(unittest.TestCase):
    def test_tee(self) -> None:
        self.assertEqual(targets_of("make | tee -a build.log"), (["build.log"], False))
        self.assertEqual(targets_of("cmd | tee a b"), (["a", "b"], False))

    def test_sed_in_place(self) -> None:
        self.assertEqual(targets_of("sed -i 's/a/b/' src/x.ts"), (["src/x.ts"], False))
        self.assertEqual(
            targets_of("sed -i.bak -e 's/a/b/' a.ts b.ts"), (["a.ts", "b.ts"], False)
        )
        self.assertEqual(targets_of("sed --in-place=.orig 's/a/b/' c.ts"), (["c.ts"], False))

    def test_sed_without_in_place_is_read_only(self) -> None:
        self.assertEqual(targets_of("sed -n 's/a/b/p' x.ts"), ([], False))

    def test_perl_in_place(self) -> None:
        self.assertEqual(targets_of("perl -pi -e 's/a/b/' x.ts"), (["x.ts"], False))

    def test_perl_inline_without_in_place_is_opaque(self) -> None:
        self.assertTrue(targets_of("perl -e 'open(F, \">x\")'")[1])

    def test_copy_move_link_install_rsync_destination(self) -> None:
        self.assertEqual(targets_of("cp -r a.ts b.ts"), (["b.ts"], False))
        self.assertEqual(targets_of("mv a b c/"), (["c"], False))
        self.assertEqual(targets_of("ln -s a b"), (["b"], False))
        self.assertEqual(targets_of("install -m 644 a b"), (["b"], False))
        self.assertEqual(targets_of("rsync -a src/ dest/"), (["dest"], False))

    def test_touch_rm_mkdir_truncate(self) -> None:
        self.assertEqual(targets_of("touch a b"), (["a", "b"], False))
        self.assertEqual(targets_of("rm -rf build/"), (["build"], False))
        self.assertEqual(targets_of("mkdir -p x/y"), (["x/y"], False))
        self.assertEqual(targets_of("truncate -s 0 x"), (["x"], False))

    def test_dd_output_file(self) -> None:
        self.assertEqual(targets_of("dd if=/dev/zero of=img.bin bs=1m"), (["img.bin"], False))

    def test_git_working_tree_mutations_are_opaque(self) -> None:
        for cmd in ("git apply p.diff", "git checkout -- src/x.ts", "git stash pop", "git reset --hard"):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_git_metadata_commands_are_fine(self) -> None:
        for cmd in ("git status", "git add -A", "git commit -m x", "git diff", "git log"):
            self.assertEqual(targets_of(cmd), ([], False), cmd)

    def test_patch_is_opaque(self) -> None:
        self.assertTrue(targets_of("patch -p1 < x.diff")[1])

    def test_inline_interpreter_code_is_opaque(self) -> None:
        for cmd in (
            "python3 -c \"open('x','w')\"",
            "node -e 'require(\"fs\").writeFileSync(\"x\",\"\")'",
            "python3 - <<EOF\nprint(1)\nEOF",
            "ruby -e 'File.write(\"x\", \"\")'",
        ):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_running_a_script_file_is_not_flagged(self) -> None:
        self.assertEqual(targets_of("python3 -m unittest discover"), ([], False))
        self.assertEqual(targets_of("node scripts/build.js"), ([], False))

    def test_eval_xargs_find_exec_are_opaque(self) -> None:
        for cmd in ('eval "$cmd"', "ls | xargs rm", "find . -name '*.o' -exec rm {} \;", "find . -delete"):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_git_init_and_clone_are_opaque(self) -> None:
        self.assertTrue(targets_of("git init src/new")[1])
        self.assertTrue(targets_of("git clone https://x/y src/clone")[1])

    def test_output_flag_programs(self) -> None:
        self.assertEqual(targets_of("sort -o src/x.ts a.txt"), (["src/x.ts"], False))
        self.assertEqual(targets_of("sort --output=src/x.ts a.txt"), (["src/x.ts"], False))
        self.assertEqual(targets_of("curl -o src/x.ts https://x"), (["src/x.ts"], False))
        self.assertEqual(targets_of("curl https://x --output src/x.ts"), (["src/x.ts"], False))
        self.assertEqual(targets_of("curl -osrc/x.ts https://x"), (["src/x.ts"], False))
        self.assertEqual(targets_of("wget -O src/x.ts https://x"), (["src/x.ts"], False))

    def test_remote_name_downloads_are_opaque(self) -> None:
        self.assertTrue(targets_of("curl -O https://x/y.ts")[1])
        self.assertTrue(targets_of("wget https://x/y.ts")[1])
        self.assertEqual(targets_of("wget --spider https://x"), ([], False))
        self.assertEqual(targets_of("curl -s https://x | head"), ([], False))

    def test_archives(self) -> None:
        self.assertEqual(targets_of("tar -xf p.tar -C src"), (["src"], False))
        self.assertEqual(targets_of("tar xzf p.tgz"), (["."], False))
        self.assertEqual(targets_of("tar -czf out.tgz src"), (["out.tgz"], False))
        self.assertEqual(targets_of("tar -tf p.tar"), ([], False))
        self.assertEqual(targets_of("unzip pkg.zip -d src"), (["src"], False))
        self.assertEqual(targets_of("unzip pkg.zip"), (["."], False))
        self.assertEqual(targets_of("unzip -l pkg.zip"), ([], False))
        self.assertEqual(targets_of("zip src/out.zip a.txt"), (["src/out.zip"], False))

    def test_editors_awk_busybox_trap_are_opaque(self) -> None:
        for cmd in (
            "awk 'BEGIN{print \"x\" > \"src/x.ts\"}' /dev/null",
            "ed src/x.ts",
            "ex -s -c 'wq src/x.ts'",
            "vim -Es -c 'w src/x.ts'",
            "busybox sh -c 'cat > src/x.ts'",
            "trap 'echo hi > src/x.ts' EXIT; true",
        ):
            self.assertTrue(targets_of(cmd)[1], cmd)

    def test_sed_empty_in_place_suffix_skips_script(self) -> None:
        self.assertEqual(targets_of("sed -i '' s/a/b/ src/x.ts"), (["src/x.ts"], False))

    def test_perl_option_cluster_consumes_script(self) -> None:
        self.assertEqual(targets_of("perl -i -pe 's/a/b/' src/x.ts"), (["src/x.ts"], False))
        self.assertEqual(targets_of("perl -pie 's/a/b/' src/x.ts"), (["src/x.ts"], False))

    def test_plain_find_is_fine(self) -> None:
        self.assertEqual(targets_of("find . -name '*.ts'"), ([], False))

    def test_nested_shell_is_recursed(self) -> None:
        self.assertEqual(targets_of('bash -c "cat > x"'), (["x"], False))
        self.assertEqual(targets_of("sh -c 'cd src && cat > y'"), (["src/y"], False))

    def test_wrappers_are_stripped(self) -> None:
        self.assertEqual(targets_of("sudo tee /etc/hosts"), (["/etc/hosts"], False))
        self.assertEqual(targets_of("env FOO=1 cat > x"), (["x"], False))
        self.assertEqual(targets_of("FOO=1 BAR=2 cat > x"), (["x"], False))
        self.assertEqual(targets_of("nohup cat > x"), (["x"], False))


class TestExtractCwd(unittest.TestCase):
    def test_cd_then_write(self) -> None:
        self.assertEqual(targets_of("cd src && cat > x.ts"), (["src/x.ts"], False))

    def test_newline_separated_commands(self) -> None:
        self.assertEqual(targets_of("cd src\ncat > x.ts"), (["src/x.ts"], False))

    def test_cd_up_is_normalized(self) -> None:
        self.assertEqual(targets_of("cd src/auth && cat > ../other.ts"), (["src/other.ts"], False))

    def test_cd_to_variable_makes_relative_writes_opaque(self) -> None:
        self.assertTrue(targets_of("cd $DIR && cat > x.ts")[1])

    def test_cd_to_variable_then_absolute_write_is_fine(self) -> None:
        self.assertEqual(targets_of("cd $DIR && cat > /tmp/x")[0], ["/tmp/x"])

    def test_variable_in_target_is_opaque(self) -> None:
        self.assertTrue(targets_of('cat > "$HOME/x"')[1])
        self.assertTrue(targets_of("cat > `mktemp`")[1])

    def test_tilde_is_expanded(self) -> None:
        targets, opaque = targets_of("cat > ~/x")
        self.assertFalse(opaque)
        self.assertEqual(targets, [os.path.expanduser("~/x")])

    def test_unbalanced_quote_is_opaque(self) -> None:
        self.assertTrue(targets_of('echo "abc')[1])

    def test_absolute_cwd(self) -> None:
        self.assertEqual(targets_of("cat > x", "/proj")[0], ["/proj/x"])


def run_gate_subprocess(event: dict, env_extra: "dict | None" = None, raw: "str | None" = None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
    env.pop("PYTHONPATH", None)
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, str(GATE_SCRIPT)],
        input=raw if raw is not None else json.dumps(event),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


class BashGateProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        self.gate_md = self.root / "spec" / "05-gate.md"
        self.gate_md.write_text("# Gate\n", encoding="utf-8")

    def tearDown(self) -> None:
        for key in list(os.environ):
            if key.startswith("GATEKIT_"):
                del os.environ[key]
        self._tmp.cleanup()

    def event(self, command: str, cwd: "str | None" = None, tool: str = "Bash") -> dict:
        return {
            "session_id": "sess-bash",
            "hook_event_name": "PreToolUse",
            "cwd": cwd or str(self.root),
            "tool_name": tool,
            "tool_input": {"command": command},
        }

    def approve(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")

    def reason(self, result: dict) -> str:
        return result["hookSpecificOutput"]["permissionDecisionReason"]


class TestSpecBeforeCode(BashGateProject):
    def test_denies_redirect_into_code_before_approval(self) -> None:
        result = bash_gate.handle(self.event("cat > src/x.ts"))
        self.assertIsNotNone(result)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("src/x.ts", self.reason(result))

    def test_denies_sed_in_place_before_approval(self) -> None:
        self.assertIsNotNone(bash_gate.handle(self.event("sed -i 's/a/b/' src/x.ts")))

    def test_allows_spec_and_docs_targets(self) -> None:
        self.assertIsNone(bash_gate.handle(self.event("cat > spec/01-prd.md")))
        self.assertIsNone(bash_gate.handle(self.event("cat > docs/notes.md")))
        self.assertIsNone(bash_gate.handle(self.event("tee README.md")))

    def test_allows_after_approval(self) -> None:
        self.approve()
        self.assertIsNone(bash_gate.handle(self.event("cat > src/x.ts")))

    def test_allows_when_no_spec_dir(self) -> None:
        (self.gate_md).unlink()
        (self.root / "spec").rmdir()
        self.assertIsNone(bash_gate.handle(self.event("cat > src/x.ts")))

    def test_read_only_commands_always_allowed(self) -> None:
        self.assertIsNone(bash_gate.handle(self.event("ls -la src | grep ts > /dev/null")))
        self.assertIsNone(bash_gate.handle(self.event("git status && cat src/x.ts")))

    def test_opaque_write_denied_before_approval(self) -> None:
        for cmd in ("git apply p.diff", "python3 -c \"open('x','w')\"", 'eval "$c"'):
            result = bash_gate.handle(self.event(cmd))
            self.assertIsNotNone(result, cmd)
            self.assertIn("cannot determine", self.reason(result))

    def test_opaque_write_allowed_after_approval(self) -> None:
        self.approve()
        self.assertIsNone(bash_gate.handle(self.event("git apply p.diff")))

    def test_relative_cd_inside_command(self) -> None:
        self.assertIsNotNone(bash_gate.handle(self.event("cd src && cat > x.ts")))
        self.assertIsNone(bash_gate.handle(self.event("cd spec && cat > 01-prd.md")))

    def test_cwd_from_event_is_honoured(self) -> None:
        (self.root / "src").mkdir()
        result = bash_gate.handle(self.event("cat > x.ts", cwd=str(self.root / "src")))
        self.assertIsNotNone(result)

    def test_reason_in_korean_when_session_is_ko(self) -> None:
        led = ledger.Ledger.load(self.root, "sess-bash")
        led.set_output_lang("ko")
        led.save()
        result = bash_gate.handle(self.event("cat > src/x.ts"))
        self.assertIn("승인", self.reason(result))
        opaque = bash_gate.handle(self.event("git apply p.diff"))
        self.assertIn("파일", self.reason(opaque))

    def test_non_bash_tool_is_ignored(self) -> None:
        self.assertIsNone(bash_gate.handle(self.event("cat > src/x.ts", tool="Read")))

    def test_missing_command_is_allowed(self) -> None:
        event = self.event("")
        event["tool_input"] = {}
        self.assertIsNone(bash_gate.handle(event))


class TestTaskScope(BashGateProject):
    def setUp(self) -> None:
        super().setUp()
        self.approve()
        task_dir = self.root / ".gatekit" / "jobs" / "job-1" / "tasks" / "auth"
        task_dir.mkdir(parents=True)
        self.task_json = task_dir / "task.json"
        self.task_json.write_text(json.dumps({"id": "auth", "write_scope": ["src/auth/**"]}))
        os.environ["GATEKIT_TASK_ID"] = "auth"
        os.environ["GATEKIT_JOB_ID"] = "job-1"

    def test_write_inside_scope_allowed(self) -> None:
        self.assertIsNone(bash_gate.handle(self.event("cat > src/auth/token.ts")))

    def test_write_outside_scope_denied(self) -> None:
        result = bash_gate.handle(self.event("cat > src/other.ts"))
        self.assertIsNotNone(result)
        self.assertIn("src/auth/**", self.reason(result))

    def test_escape_via_cd_denied(self) -> None:
        self.assertIsNotNone(bash_gate.handle(self.event("cd src/auth && cat > ../other.ts")))

    def test_second_command_in_chain_is_checked(self) -> None:
        self.assertIsNotNone(bash_gate.handle(self.event("cat > src/auth/a.ts && cat > spec/01-prd.md")))

    def test_opaque_denied_for_scoped_worker(self) -> None:
        self.assertIsNotNone(bash_gate.handle(self.event("git checkout -- src/auth/a.ts")))

    def test_read_only_task_denies_any_write_but_allows_reads(self) -> None:
        self.task_json.write_text(json.dumps({"id": "auth", "write_scope": "read-only"}))
        self.assertIsNotNone(bash_gate.handle(self.event("cat > src/auth/token.ts")))
        self.assertIsNone(bash_gate.handle(self.event("cat src/auth/token.ts | wc -l")))

    def test_outside_root_denied(self) -> None:
        self.assertIsNotNone(bash_gate.handle(self.event("cat > /tmp/escape.ts")))


class TestSubprocessContract(BashGateProject):
    def test_deny_is_json_on_stdout_exit_zero(self) -> None:
        code, out, _ = run_gate_subprocess(self.event("cat > src/x.ts"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_allow_prints_nothing_exit_zero(self) -> None:
        code, out, _ = run_gate_subprocess(self.event("ls"))
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_internal_error_still_exits_zero(self) -> None:
        code, out, _ = run_gate_subprocess({}, raw="this is not json")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

    def test_handler_exception_is_logged_and_allows(self) -> None:
        event = self.event("cat > src/x.ts")
        event["tool_input"] = {"command": ["not", "a", "string"]}
        code, out, _ = run_gate_subprocess(event)
        self.assertEqual(code, 0)


class TestRegistration(unittest.TestCase):
    def test_hooks_json_routes_bash_to_this_gate(self) -> None:
        hooks_path = pathlib.Path(__file__).resolve().parents[1] / "hooks" / "hooks.json"
        hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
        matchers = {entry["matcher"]: entry for entry in hooks["hooks"]["PreToolUse"]}
        self.assertIn("Bash", matchers)
        self.assertIn("gates/bash.py", matchers["Bash"]["hooks"][0]["command"])

    def test_doctor_lists_bash_gate(self) -> None:
        from gatekit import doctor

        self.assertIn("bash.py", doctor.GATE_SCRIPTS)


if __name__ == "__main__":
    unittest.main()
