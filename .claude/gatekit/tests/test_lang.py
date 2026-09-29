"""Tests for gatekit.lang — output language detection (ko/en)."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import unittest

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import lang

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[1]


class TestDetect(unittest.TestCase):
    def test_empty_is_en(self) -> None:
        self.assertEqual(lang.detect(""), "en")

    def test_none_is_en(self) -> None:
        self.assertEqual(lang.detect(None), "en")  # type: ignore[arg-type]

    def test_pure_english_is_en(self) -> None:
        self.assertEqual(lang.detect("Please build the login screen"), "en")

    def test_pure_korean_is_ko(self) -> None:
        self.assertEqual(lang.detect("로그인 화면을 만들어줘"), "ko")

    def test_jamo_counts_as_hangul(self) -> None:
        self.assertEqual(lang.detect("ㅇㅇ ㄱㄱ"), "ko")

    def test_no_letters_at_all_is_en(self) -> None:
        self.assertEqual(lang.detect("123 !!! ---"), "en")
        self.assertEqual(lang.detect("   "), "en")

    def test_mixed_above_threshold_is_ko(self) -> None:
        # 6 Hangul letters, 4 Latin letters -> 60% >= 30%
        self.assertEqual(lang.detect("로그인화면 auth"), "ko")

    def test_mixed_below_threshold_is_en(self) -> None:
        # 2 Hangul vs 40 Latin letters -> ~4.8% < 30%
        text = "Implement the authentication middleware carefully 로그"
        self.assertEqual(lang.detect(text), "en")

    def test_threshold_is_thirty_percent_inclusive(self) -> None:
        # exactly 3 Hangul out of 10 letters == 30% -> ko
        self.assertEqual(lang.detect("가나다abcdefg"), "ko")
        # 2 out of 10 == 20% -> en
        self.assertEqual(lang.detect("가나abcdefgh"), "en")

    def test_punctuation_and_digits_are_not_counted(self) -> None:
        # Digits and separators must not dilute the ratio: 3 Hangul letters vs
        # 3 Latin letters is 50% even though most characters are ASCII.
        self.assertEqual(lang.detect("v1.2.3 / 100% -- 고쳐줘 now"), "ko")

    def test_path_tokens_do_not_count(self) -> None:
        # "src/hello.ts 만들어줘" must not flip to English. Paths and
        # identifiers are named, not written.
        self.assertEqual(lang.detect("src/auth/token.ts 를 고쳐줘"), "ko")
        self.assertEqual(lang.detect("src/hello.ts 만들어줘"), "ko")
        self.assertEqual(lang.detect("README.md 읽어줘"), "ko")
        self.assertEqual(lang.detect("`user_id` 컬럼 추가"), "ko")

    def test_english_around_a_path_stays_english(self) -> None:
        self.assertEqual(lang.detect("please create src/hello.ts now"), "en")
        self.assertEqual(lang.detect("make src/hello.ts"), "en")

    def test_trailing_period_is_not_an_identifier_marker(self) -> None:
        self.assertEqual(lang.detect("Hello world."), "en")
        self.assertEqual(lang.detect("안녕하세요 world."), "ko")

    def test_only_identifiers_is_english(self) -> None:
        self.assertEqual(lang.detect("src/a.ts src/b.ts"), "en")

    def test_cjk_han_is_not_hangul(self) -> None:
        self.assertEqual(lang.detect("漢字 only here"), "en")


class TestRun(unittest.TestCase):
    def test_run_prints_detected_language(self) -> None:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = lang.run(["안녕하세요"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "ko")

    def test_run_without_args_is_en(self) -> None:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = lang.run([])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "en")

    def test_run_joins_multiple_args(self) -> None:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            lang.run(["hello", "world"])
        self.assertEqual(buf.getvalue().strip(), "en")


class TestRunFromFileAndStdin(unittest.TestCase):
    """`lang --file/--stdin/--lines` replace `lang "$(head -40 file)"`."""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)

    def detect_cli(self, argv, stdin_text=None) -> str:
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        old_stdin = sys.stdin
        if stdin_text is not None:
            sys.stdin = io.StringIO(stdin_text)
        try:
            with redirect_stdout(buf):
                self.assertEqual(lang.run(argv), 0)
        finally:
            sys.stdin = old_stdin
        return buf.getvalue().strip()

    def test_file_is_read_as_utf8(self) -> None:
        path = self.dir / "prd.md"
        path.write_text("# 제품 기획서\n사용자가 겪는 문제를 정리합니다\n", encoding="utf-8")
        self.assertEqual(self.detect_cli(["--file", str(path)]), "ko")

    def test_file_with_bom_and_crlf(self) -> None:
        path = self.dir / "prd.md"
        path.write_bytes("안녕하세요 기획서\r\n".encode("utf-8-sig"))
        self.assertEqual(self.detect_cli(["--file", str(path)]), "ko")

    def test_lines_limit_ignores_later_lines(self) -> None:
        path = self.dir / "mixed.md"
        path.write_text("hello world of english text\n" + "한글 " * 200 + "\n", encoding="utf-8")
        self.assertEqual(self.detect_cli(["--file", str(path), "--lines", "1"]), "en")
        self.assertEqual(self.detect_cli(["--file", str(path), "--lines", "2"]), "ko")
        self.assertEqual(self.detect_cli(["--file", str(path)]), "ko")

    def test_text_with_quotes_dollar_and_backticks_passes_through_a_file(self) -> None:
        path = self.dir / "args.txt"
        path.write_text('그는 "안녕" 이라고 말했다 $HOME `date` \'끝\'', encoding="utf-8")
        self.assertEqual(self.detect_cli(["--file", str(path)]), "ko")

    def test_stdin(self) -> None:
        self.assertEqual(self.detect_cli(["--stdin"], "이 문서는 한국어입니다\n"), "ko")
        self.assertEqual(self.detect_cli(["--stdin"], "plain english\n"), "en")

    def test_missing_file_is_exit_2(self) -> None:
        import io
        from contextlib import redirect_stderr

        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(lang.run(["--file", str(self.dir / "nope.md")]), 2)
        self.assertIn("cannot read", err.getvalue())

    def test_bad_lines_value_is_exit_2(self) -> None:
        import io
        from contextlib import redirect_stderr

        with redirect_stderr(io.StringIO()):
            self.assertEqual(lang.run(["--file", "x", "--lines", "many"]), 2)
            self.assertEqual(lang.run(["--file", "x", "--lines", "-3"]), 2)

    def test_cli_entry_point_from_foreign_cwd(self) -> None:
        path = self.dir / "prd.md"
        path.write_text("한국어 문서입니다\n", encoding="utf-8")
        launcher = PLUGIN_DIR / "bin" / "gatekit.py"
        proc = subprocess.run(
            [sys.executable, str(launcher), "lang", "--file", str(path), "--lines", "40"],
            cwd=str(self.dir), capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ko")


class TestModuleEntryPoint(unittest.TestCase):
    """`python3 -m gatekit lang ...` must work with cwd=plugin and no PYTHONPATH."""

    def test_python_m_gatekit_lang(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, "-m", "gatekit", "lang", "안녕하세요"],
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
