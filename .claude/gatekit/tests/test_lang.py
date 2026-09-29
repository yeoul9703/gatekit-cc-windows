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
