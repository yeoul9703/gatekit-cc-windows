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
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".gatekit"))
            event = json.dumps({"session_id": "t", "cwd": tmp, "prompt": "한글 테스트 입니다"},
                               ensure_ascii=False).encode("utf-8")
            result = _run(["_gate", "prompt"], event, cwd=tmp)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout.decode("utf-8")  # must be valid UTF-8
        self.assertIn("output_lang=ko", out)

    def test_cli_output_is_utf8_without_replacement_characters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(["doctor", "--root", tmp], cwd=tmp)
        text = result.stdout.decode("utf-8")  # raises if not valid UTF-8
        self.assertNotIn("�", text)
        self.assertIn("gatekit doctor", text)


if __name__ == "__main__":
    unittest.main()
