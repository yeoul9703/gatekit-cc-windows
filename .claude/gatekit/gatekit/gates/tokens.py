"""Task gate: every colour literal a task wrote must be a design token.

This is a *task* gate, not a hook. ``jobs.run_gates`` runs it in the project
root when the task is completed, with the task's ``write_scope`` globs as
arguments::

    uv run --project .claude/gatekit --frozen python .claude/gatekit/bin/gatekit.py _gate tokens [--root DIR]
        [--lang ko|en] [--json] GLOB [GLOB...]

The exit code is the verdict: ``0`` ok, ``1`` fail, ``3`` unverified. An
internal error is ``3`` with a one-line reason — never a traceback, never a
silent ``0``, because "could not check" is not "checked and fine".

Scope at ADR-0008 acceptance: **colours only**. Hex (``#rgb``, ``#rgba``,
``#rrggbb``, ``#rrggbbaa``) and ``rgb()``/``rgba()``/``hsl()``/``hsla()``
literals are compared, normalized, against every colour value found in
``spec/tokens.json``. Lengths and font families are an open question in the
ADR and are not scanned. Comments and ``url(...)`` contents are ignored.
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import design, verdict  # noqa: E402

#: File kinds the gate knows how to read. Anything else is skipped silently.
EXTENSIONS = frozenset({
    ".css", ".scss", ".less", ".html", ".htm", ".vue", ".svelte",
    ".jsx", ".tsx", ".js", ".ts", ".astro", ".mdx",
})

#: Kinds where ``//`` opens a line comment. CSS and HTML are not among them.
LINE_COMMENT_EXTENSIONS = frozenset({
    ".scss", ".less", ".vue", ".svelte", ".jsx", ".tsx", ".js", ".ts", ".astro", ".mdx",
})

SKIP_DIRS = frozenset({"node_modules", ".git", "dist", "build"})
MAX_BYTES = 1_000_000

#: Keywords that are colours but never tokens.
NEVER_VIOLATIONS = frozenset({"transparent", "currentcolor", "inherit"})

_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![0-9a-zA-Z])")
_FUNC_RE = re.compile(r"(?<![\w-])(?:rgba?|hsla?)\s*\([^)]*\)", re.IGNORECASE)
_URL_RE = re.compile(r"url\([^)]*\)", re.IGNORECASE)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
#: ``//`` not preceded by ``:`` so ``http://`` survives.
_LINE_COMMENT_RE = re.compile(r"(?<!:)//[^\n]*")

_MESSAGES = {
    "en": {
        "summary": "tokens: {verdict} — {literals} literals, {violations} violations, {files} files scanned",
        "no_tokens": "tokens: unverified — spec/tokens.json is absent, unreadable, or has no colour tokens",
        "violation": "{path}:{line}: {literal} is not a design token",
        "nearest": " (nearest: {name} = {value})",
        "error": "tokens: unverified — internal error: {error}",
    },
    "ko": {
        "summary": "tokens: {verdict} — 리터럴 {literals}개, 위반 {violations}개, 파일 {files}개 검사",
        "no_tokens": "tokens: unverified — spec/tokens.json 이 없거나 읽을 수 없거나 색상 토큰이 없습니다",
        "violation": "{path}:{line}: {literal} 은(는) 디자인 토큰이 아닙니다",
        "nearest": " (가장 가까운 토큰: {name} = {value})",
        "error": "tokens: unverified — 내부 오류: {error}",
    },
}


def _msg(lang: str, key: str, **kw: Any) -> str:
    table = _MESSAGES.get(lang) or _MESSAGES["en"]
    return table[key].format(**kw)


# ------------------------------------------------------------------ colours


def normalize_colour(literal: str) -> str:
    """Canonical spelling: lowercase, short hex expanded, no whitespace."""
    text = literal.strip().lower()
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) in (3, 4):
            digits = "".join(ch * 2 for ch in digits)
        return "#" + digits
    return re.sub(r"\s+", "", text)


def _is_colour(text: str) -> bool:
    return bool(_HEX_RE.fullmatch(text) or _FUNC_RE.fullmatch(text))


def _leaf_values(value: Any) -> Iterable[Any]:
    """Every scalar under *value*, treating ``{"value": x}`` as the scalar x."""
    if isinstance(value, dict):
        if "value" in value:
            yield value["value"]
            return
        for child in value.values():
            yield from _leaf_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _leaf_values(child)
    else:
        yield value


def known_colours(data: Dict[str, Any]) -> Dict[str, Tuple[str, str]]:
    """``{normalized: (group.name, original)}`` for every colour-shaped token."""
    known: Dict[str, Tuple[str, str]] = {}
    for group, members in design.token_groups(data).items():
        for name, value in members.items():
            for leaf in _leaf_values(value):
                if isinstance(leaf, str) and _is_colour(leaf.strip()):
                    known.setdefault(normalize_colour(leaf), ("%s.%s" % (group, name), leaf))
    return known


def allowed_colours(data: Dict[str, Any]) -> set:
    allow = data.get("allow")
    values = allow.get("color", []) if isinstance(allow, dict) else []
    out = set(NEVER_VIOLATIONS)
    for item in values:
        if isinstance(item, str):
            out.add(normalize_colour(item))
    return out


def _rgb(normalized_hex: str) -> Optional[Tuple[int, int, int]]:
    digits = normalized_hex[1:]
    if len(digits) < 6:
        return None
    try:
        return tuple(int(digits[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def nearest_token(literal: str, known: Dict[str, Tuple[str, str]]) -> Optional[Tuple[str, str]]:
    """Closest hex token by RGB distance, or ``None`` when nothing comparable."""
    target = _rgb(normalize_colour(literal)) if literal.startswith("#") else None
    if target is None:
        return None
    best: Optional[Tuple[float, str, str]] = None
    for norm, (name, original) in known.items():
        rgb = _rgb(norm) if norm.startswith("#") else None
        if rgb is None:
            continue
        dist = math.dist(target, rgb)
        if best is None or dist < best[0]:
            best = (dist, name, original)
    return (best[1], best[2]) if best else None


# ------------------------------------------------------------------- files


def _blank(match: "re.Match[str]") -> str:
    """Replace a match with spaces, keeping newlines so line numbers hold."""
    return re.sub(r"[^\n]", " ", match.group(0))


def strip_ignored(text: str, suffix: str) -> str:
    text = _BLOCK_COMMENT_RE.sub(_blank, text)
    text = _HTML_COMMENT_RE.sub(_blank, text)
    if suffix in LINE_COMMENT_EXTENSIONS:
        text = _LINE_COMMENT_RE.sub(_blank, text)
    return _URL_RE.sub(_blank, text)


def _read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _scannable(path: pathlib.Path, root: pathlib.Path) -> Optional[pathlib.Path]:
    """The resolved path when it is a readable file inside *root*, else ``None``.

    Containment is judged on the *resolved* path, so ``../x`` in a glob and a
    symlink pointing outside the project both fall out here rather than being
    read and reported on.
    """
    if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
        return None
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return None
    if any(part in SKIP_DIRS for part in rel.parts):
        return None
    if resolved.stat().st_size > MAX_BYTES:
        return None
    return resolved


def collect_files(root: pathlib.Path, globs: Iterable[str]) -> List[pathlib.Path]:
    """Resolved, de-duplicated files under *root* (itself resolved) matching *globs*."""
    root = root.resolve()
    seen: Dict[pathlib.Path, None] = {}
    for pattern in globs:
        pattern = str(pattern).strip()
        if not pattern:
            continue
        for path in sorted(root.glob(pattern)):
            resolved = _scannable(path, root)
            if resolved is not None:
                seen.setdefault(resolved, None)
    return sorted(seen)


def find_literals(text: str) -> List[Tuple[int, str]]:
    """``(line, literal)`` for every colour literal in already-stripped text."""
    found: List[Tuple[int, str]] = []
    for regex in (_FUNC_RE, _HEX_RE):
        for match in regex.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append((line, match.group(0)))
    found.sort()
    return found


# -------------------------------------------------------------------- gate


def check(root: pathlib.Path, globs: Iterable[str]) -> Dict[str, Any]:
    data = design.load_tokens(root)
    known = known_colours(data) if data else {}
    if not known:
        return {"verdict": verdict.UNVERIFIED, "reason": "no_tokens",
                "files": 0, "literals": 0, "violations": []}
    allowed = allowed_colours(data)
    files = collect_files(root, globs)
    if not files:
        return {"verdict": verdict.UNVERIFIED, "reason": "no_files",
                "files": 0, "literals": 0, "violations": []}

    literals = 0
    violations: List[Dict[str, Any]] = []
    for path in files:
        text = strip_ignored(_read_text(path), path.suffix.lower())
        rel = path.relative_to(root).as_posix()
        for line, literal in find_literals(text):
            literals += 1
            norm = normalize_colour(literal)
            if norm in known or norm in allowed:
                continue
            near = nearest_token(literal, known)
            violations.append({
                "path": rel,
                "line": line,
                "literal": literal,
                "nearest": {"name": near[0], "value": near[1]} if near else None,
            })
    return {
        "verdict": verdict.FAIL if violations else verdict.OK,
        "reason": "",
        "files": len(files),
        "literals": literals,
        "violations": violations,
    }


EXIT_CODES = {verdict.OK: 0, verdict.FAIL: 1, verdict.UNVERIFIED: 3}


def render(report: Dict[str, Any], lang: str) -> str:
    if report.get("reason") == "no_tokens":
        return _msg(lang, "no_tokens")
    lines = [_msg(lang, "summary", verdict=report["verdict"], literals=report["literals"],
                  violations=len(report["violations"]), files=report["files"])]
    for item in report["violations"]:
        line = _msg(lang, "violation", path=item["path"], line=item["line"], literal=item["literal"])
        if item.get("nearest"):
            line += _msg(lang, "nearest", name=item["nearest"]["name"], value=item["nearest"]["value"])
        lines.append(line)
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="tokens", add_help=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--lang", default="ko", choices=("ko", "en"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("globs", nargs="*")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse already printed its message
        return 3 if exc.code else 0
    lang = args.lang
    try:
        root = pathlib.Path(args.root).resolve()
        report = check(root, args.globs)
        if args.json:
            print(json.dumps({k: v for k, v in report.items() if k != "reason"}, ensure_ascii=False))
        else:
            print(render(report, lang))
        return EXIT_CODES[report["verdict"]]
    except Exception as exc:  # noqa: BLE001 — a gate reports, it never crashes
        if args.json:
            print(json.dumps({"verdict": verdict.UNVERIFIED, "files": 0, "literals": 0,
                              "violations": [], "error": str(exc)}, ensure_ascii=False))
        else:
            print(_msg(lang, "error", error=exc))
        return 3


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
