"""Output language detection.

gatekit is open source and must never default to Korean. This module answers a
single question — "which language did the user write in?" — from the text of
their prompt, and the answer is stored once per session in the ledger. Every
user-facing string a command emits follows it.

Detection counts letters only: Hangul syllables and jamo against Latin letters.
Digits and punctuation are ignored, and so are whitespace-delimited tokens that
are paths or code identifiers (they contain ``/``, ``.``, ``_``, ``\\`` or a
backtick inside them), so ``src/auth/token.ts 를 고쳐줘`` is Korean even though
most of its characters are ASCII. Without this rule, ``src/hello.ts 만들어줘``
would misdetect as English.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from typing import List, Optional

KO = "ko"
EN = "en"

#: Hangul share of all counted letters at or above which the text is Korean.
HANGUL_THRESHOLD = 0.30

# Unicode blocks holding Hangul: syllables, compatibility jamo (ㅇㅋ), the
# original jamo block, and the two extended-jamo blocks.
_HANGUL_RANGES = (
    (0xAC00, 0xD7A3),  # Hangul syllables
    (0x1100, 0x11FF),  # Hangul jamo
    (0x3130, 0x318F),  # Hangul compatibility jamo
    (0xA960, 0xA97F),  # Hangul jamo extended-A
    (0xD7B0, 0xD7FF),  # Hangul jamo extended-B
)


def _is_hangul(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _HANGUL_RANGES)


#: Characters that mark a whitespace-delimited token as a path or a code
#: identifier once its surrounding punctuation is stripped: ``src/hello.ts``,
#: ``user_id``, ``foo.bar``, ```code```. Such tokens are named, not written,
#: and must not drag a short Korean request to English.
_IDENTIFIER_CHARS = set("/._\\`")
_EDGE_PUNCT = "\"'()[]{}<>,;:!?…"


def prose_only(text: str) -> str:
    """*text* with path and identifier tokens removed."""
    kept = []
    for token in str(text).split():
        core = token.strip(_EDGE_PUNCT)
        if not core:
            continue
        if any(ch in _IDENTIFIER_CHARS for ch in core.rstrip(".")):
            continue
        kept.append(core)
    return " ".join(kept)


def _letter_counts(text: Optional[str]) -> tuple:
    """Return ``(hangul, letters)`` for the prose part of *text*."""
    if not text:
        return (0, 0)

    hangul = 0
    letters = 0
    for char in prose_only(text):
        if not char.isalpha():
            continue
        # Guard against scripts we do not classify (Han, Cyrillic, ...) being
        # counted as "not Korean" and skewing the ratio: only Hangul and Latin
        # participate in the denominator.
        if _is_hangul(char):
            hangul += 1
            letters += 1
        elif "LATIN" in unicodedata.name(char, ""):
            letters += 1
    return (hangul, letters)


def carries_signal(text: Optional[str]) -> bool:
    """Whether *text* says anything about which language the user is writing in.

    `"1"`, `"2."`, `"ok 3"` and a bare path carry none: they are the same
    keystrokes in either language. Treating a short numbered reply (e.g. an
    `AskUserQuestion` option) as an English signal would silently switch a
    Korean session to English mid-interview.

    A caller that refreshes a stored language must ask this first; `detect`
    alone cannot tell "no evidence" from "evidence of English", because it
    has to return one of the two either way.
    """
    return _letter_counts(text)[1] > 0


def detect(text: Optional[str]) -> str:
    """Return ``"ko"`` or ``"en"`` for *text*.

    Korean when Hangul letters are at least 30% of all letters. Empty text, or
    text with no letters at all, is English — callers that must not overwrite
    a known language with that fallback check :func:`carries_signal` first.
    """
    hangul, letters = _letter_counts(text)
    if letters == 0:
        return EN
    return KO if (hangul / letters) >= HANGUL_THRESHOLD else EN


def _read_lines(stream, limit: Optional[int]) -> str:
    lines = []
    for line in stream:
        if limit is not None and len(lines) >= limit:
            break
        lines.append(line)
    return "".join(lines)


def run(argv: List[str]) -> int:
    """``gatekit lang [--file PATH | --stdin] [--lines N] [text...]``.

    Prints the detected language. ``--file`` / ``--stdin`` read the text from a
    UTF-8 file or from stdin instead of the command line, so callers never have
    to push arbitrary text (quotes, ``$``, backticks, newlines) through a shell
    argument; ``--lines N`` keeps only the first N lines of that input.
    Positional words are still accepted and joined with spaces.
    """
    file_path = None
    use_stdin = False
    limit: Optional[int] = None
    words: List[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--file" and i + 1 < len(argv):
            file_path = argv[i + 1]
            i += 2
        elif arg == "--lines" and i + 1 < len(argv):
            try:
                limit = int(argv[i + 1])
            except ValueError:
                print("lang: --lines needs an integer", file=sys.stderr)
                return 2
            if limit < 0:
                print("lang: --lines must not be negative", file=sys.stderr)
                return 2
            i += 2
        elif arg == "--stdin":
            use_stdin = True
            i += 1
        else:
            words.append(arg)
            i += 1

    if file_path is not None:
        try:
            with open(file_path, "r", encoding="utf-8-sig", errors="replace") as handle:
                text = _read_lines(handle, limit)
        except OSError as exc:
            print("lang: cannot read %s: %s" % (file_path, exc), file=sys.stderr)
            return 2
    elif use_stdin:
        text = _read_lines(sys.stdin, limit)
    else:
        text = " ".join(words)
    print(detect(text))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
