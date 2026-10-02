"""Hooks and the CLI must speak UTF-8 on stdin/stdout whatever the console
code page is (Windows pipes default to cp1252/cp949)."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

LAUNCHER = pathlib.Path(__file__).resolve().parent.parent / "bin" / "gatekit.py"


def _run(args, stdin=b"", cwd=None):
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "cp1252"  # simulate a legacy console code page
    return subprocess.run([sys.executable, str(LAUNCHER)] + args, input=stdin,
                          capture_output=True, env=env, cwd=cwd)


class TestStdioUtf8(unittest.TestCase):
    def test_korean_prompt_on_stdin_is_read_as_utf8(self) -> None:
        prompt = "한글 테스트 입니다"
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".gatekit"))
            event = json.dumps({"session_id": "t", "cwd": tmp, "prompt": prompt},
                               ensure_ascii=False).encode("utf-8")
            result = _run(["_gate", "prompt"], event, cwd=tmp)
            ledger_path = pathlib.Path(tmp) / ".gatekit" / "runs" / "t.json"
            stored = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout.decode("utf-8")  # must be valid UTF-8
        self.assertIn("output_lang=ko", out)
        # Read as cp1252 the same bytes are 26 characters, not 10: the count the
        # gate recorded says which decoding it used.
        chars = [e["detail"]["chars"] for e in stored["events"] if e["kind"] == "prompt"]
        self.assertEqual(chars, [len(prompt)])

    def test_an_english_session_is_denied_in_korean_through_the_registered_hooks(self) -> None:
        """The two hooks as settings.json registers them (``bin/gatekit.py _gate <name>``),
        on a console whose code page cannot hold Korean: an English prompt, then a
        write before the gate is approved. The denial arrives, in Korean, as UTF-8."""
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".gatekit"))
            os.makedirs(os.path.join(tmp, "spec"))
            with open(os.path.join(tmp, "spec", "05-gate.md"), "w", encoding="utf-8") as handle:
                handle.write("# Gate\n")
            prompt = json.dumps({"session_id": "t", "cwd": tmp, "hook_event_name": "UserPromptSubmit",
                                 "prompt": "Please build the login screen now."}).encode("utf-8")
            first = _run(["_gate", "prompt"], prompt, cwd=tmp)
            ledger_path = pathlib.Path(tmp) / ".gatekit" / "runs" / "t.json"
            stored = json.loads(ledger_path.read_text(encoding="utf-8"))
            write = json.dumps({"session_id": "t", "cwd": tmp, "hook_event_name": "PreToolUse",
                                "tool_name": "Write",
                                "tool_input": {"file_path": os.path.join(tmp, "src", "app.ts")}}
                               ).encode("utf-8")
            second = _run(["_gate", "write"], write, cwd=tmp)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(stored["output_lang"], "ko")
        self.assertEqual(second.returncode, 0, second.stderr)
        block = json.loads(second.stdout.decode("utf-8"))["hookSpecificOutput"]
        self.assertEqual(block["permissionDecision"], "deny")
        self.assertIn("승인 전에는 코드를 쓸 수 없습니다", block["permissionDecisionReason"])
        self.assertIn("src/app.ts", block["permissionDecisionReason"])

    def test_cli_output_is_utf8_without_replacement_characters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(["doctor", "--root", tmp], cwd=tmp)
        text = result.stdout.decode("utf-8")  # raises if not valid UTF-8
        self.assertNotIn("�", text)
        self.assertIn("gatekit 닥터", text)
        self.assertIn("설치 파일", text)


if __name__ == "__main__":
    unittest.main()
