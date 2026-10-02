"""Tests for gatekit.lang — the output language is always Korean."""
from __future__ import annotations

import io
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import lang

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[1]


class TestDetect(unittest.TestCase):
    def test_english_text_is_ko(self) -> None:
        for text in ("Please build the login screen", "make src/hello.ts", "Hello world.",
                     "Implement the authentication middleware carefully 로그"):
            self.assertEqual(lang.detect(text), "ko", text)

    def test_korean_text_is_ko(self) -> None:
        for text in ("로그인 화면을 만들어줘", "ㅇㅇ ㄱㄱ", "src/auth/token.ts 를 고쳐줘"):
            self.assertEqual(lang.detect(text), "ko", text)

    def test_text_without_letters_is_ko(self) -> None:
        for text in ("", "   ", "123 !!! ---", "src/a.ts src/b.ts", "漢字"):
            self.assertEqual(lang.detect(text), "ko", repr(text))

    def test_none_and_no_argument_are_ko(self) -> None:
        self.assertEqual(lang.detect(None), "ko")
        self.assertEqual(lang.detect(), "ko")


class TestRun(unittest.TestCase):
    """`gatekit lang` keeps the arguments the skill documents pass and prints ko."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)

    def printed(self, argv, stdin_text=None) -> str:
        buf, err = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        if stdin_text is not None:
            sys.stdin = io.StringIO(stdin_text)
        try:
            with redirect_stdout(buf), redirect_stderr(err):
                self.assertEqual(lang.run(argv), 0, argv)
        finally:
            sys.stdin = old_stdin
        self.assertEqual(err.getvalue(), "", argv)
        return buf.getvalue().strip()

    def test_words_in_any_language_print_ko(self) -> None:
        self.assertEqual(self.printed(["안녕하세요"]), "ko")
        self.assertEqual(self.printed(["hello", "world"]), "ko")
        self.assertEqual(self.printed([]), "ko")

    def test_an_english_file_prints_ko(self) -> None:
        path = self.dir / "prd.md"
        path.write_text("# Product requirements\nThe user cannot log in.\n", encoding="utf-8")
        self.assertEqual(self.printed(["--file", str(path)]), "ko")
        self.assertEqual(self.printed(["--file", str(path), "--lines", "40"]), "ko")

    def test_english_stdin_prints_ko(self) -> None:
        self.assertEqual(self.printed(["--stdin"], "plain english\n"), "ko")
        self.assertEqual(self.printed(["--stdin", "--lines", "1"], "plain english\n"), "ko")

    def test_arguments_are_not_read(self) -> None:
        """A file that is not there and a count that is not a number are no error:
        the answer does not depend on them."""
        self.assertEqual(self.printed(["--file", str(self.dir / "nope.md")]), "ko")
        self.assertEqual(self.printed(["--file", "x", "--lines", "many"]), "ko")
        self.assertEqual(self.printed(["--file", "x", "--lines", "-3"]), "ko")
        self.assertEqual(self.printed(["--file"]), "ko")

    def test_cli_entry_point_from_foreign_cwd(self) -> None:
        path = self.dir / "prd.md"
        path.write_text("English requirements only\n", encoding="utf-8")
        launcher = PLUGIN_DIR / "bin" / "gatekit.py"
        proc = subprocess.run(
            [sys.executable, str(launcher), "lang", "--file", str(path), "--lines", "40"],
            cwd=str(self.dir), capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ko")


class TestModuleEntryPoint(unittest.TestCase):
    """`python -m gatekit lang ...` must work with cwd=.claude/gatekit and no PYTHONPATH."""

    def test_python_m_gatekit_lang(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, "-m", "gatekit", "lang", "build the login screen"],
            cwd=str(PLUGIN_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ko")

    def test_python_m_gatekit_help(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, "-m", "gatekit", "--help"],
            cwd=str(PLUGIN_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("lang", proc.stdout)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
