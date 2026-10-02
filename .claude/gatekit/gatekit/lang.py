"""Output language: always Korean.

This kit is Korean-only. Every user-facing string a command or a gate emits is
Korean, so there is nothing to detect: :func:`detect` answers ``"ko"`` whatever
the text is, and the session ledger stores that answer.

The ``gatekit lang`` subcommand is kept because the skill documents still call
it at their first step. It accepts the arguments it used to take and prints
``ko``.
"""
from __future__ import annotations

import sys
from typing import List, Optional

KO = "ko"


def detect(text: Optional[str] = None) -> str:
    """Return ``"ko"``. *text* is accepted and not read."""
    return KO


def run(argv: List[str]) -> int:
    """``gatekit lang [--file PATH | --stdin] [--lines N] [text...]``.

    Prints ``ko`` and exits 0. The arguments are accepted and ignored: no file
    is opened and stdin is not read.
    """
    print(detect())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
