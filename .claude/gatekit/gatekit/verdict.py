"""The gatekit verdict vocabulary: exactly four states, never rounded.

The whole point of this module is the fourth state. ``unverified`` means "we
did not check" — a timeout, a missing tool, an absent artifact list. Rounding it
to ``ok`` invents evidence; rounding it to ``fail`` invents a defect. Both are
lies, so :func:`aggregate` keeps it distinct and every caller must too.

JSON always carries the English token; :func:`render` produces the localized
label for human-facing text only.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

OK = "ok"
WARN = "warn"
FAIL = "fail"
UNVERIFIED = "unverified"

#: Severity, most severe first. :func:`aggregate` returns the first member of
#: this list that appears in its input.
ORDER = [FAIL, UNVERIFIED, WARN, OK]

_LABELS: Dict[str, Dict[str, str]] = {
    "en": {OK: "OK", WARN: "WARN", FAIL: "FAIL", UNVERIFIED: "UNVERIFIED"},
    "ko": {OK: "통과", WARN: "주의", FAIL: "실패", UNVERIFIED: "미검증"},
}

_DEFAULT_LANG = "ko"


def is_valid(value: Any) -> bool:
    """True when *value* is one of the four vocabulary tokens."""
    return value in ORDER


def _coerce(item: Any) -> str:
    """Normalize one input item to a vocabulary token.

    Accepts a bare token or a result dict carrying a ``verdict`` key, which is
    what :mod:`gatekit.contract` and :mod:`gatekit.doctor` produce. Anything
    unrecognized becomes ``unverified``: an unreadable result is by definition
    not a checked one.
    """
    if isinstance(item, dict):
        item = item.get("verdict")
    return item if is_valid(item) else UNVERIFIED


def aggregate(verdicts: Iterable[Any]) -> str:
    """Combine verdicts into one, worst-first.

    Empty input is ``unverified``, not ``ok``: having checked nothing is not
    the same as having checked everything successfully.
    """
    seen = {_coerce(item) for item in verdicts}
    if not seen:
        return UNVERIFIED
    for candidate in ORDER:
        if candidate in seen:
            return candidate
    return UNVERIFIED  # pragma: no cover - unreachable, _coerce covers ORDER


def render(verdict: str, lang: Optional[str] = None) -> str:
    """Return the human-readable label for *verdict* in *lang*.

    No language, or an unknown one, renders in Korean. Unknown verdicts
    render as ``unverified``.
    """
    table = _LABELS.get(lang or _DEFAULT_LANG, _LABELS[_DEFAULT_LANG])
    return table.get(_coerce(verdict), table[UNVERIFIED])
