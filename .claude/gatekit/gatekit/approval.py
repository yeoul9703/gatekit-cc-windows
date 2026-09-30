"""Hash-anchored approvals: ``.gatekit/approvals.json``.

An approval binds a human decision to *exact file content*, not to a filename.
Approving ``spec/05-gate.md`` records its SHA-256; if a single byte changes
afterwards, :func:`check` reports ``fail`` (stale approval) rather than quietly
carrying the old sign-off forward.

Three outcomes, never two:

===========  ==========================================================
``ok``       an approval exists and the file still hashes to it
``fail``     an approval exists but the content changed (or vanished)
``unverified`` no approval was ever recorded — not a failure, just unasked
===========  ==========================================================

This module never writes to the approved file. Rewriting content to satisfy a
recorded hash would defeat the entire mechanism.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys
from typing import Any, Dict, List, Optional

from . import config, paths, verdict

VERSION = 1

_CHUNK = 65536


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _normalize(relpath: str) -> str:
    """Canonical POSIX-relative form used as the approval key."""
    text = str(relpath).strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def sha256_file(path: pathlib.Path) -> str:
    """Hex SHA-256 of *path*, or ``""`` when it is unreadable or absent."""
    import hashlib  # lazy: OpenSSL load costs ~8 ms on the hot hook path
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(_CHUNK), b""):
                digest.update(chunk)
    except (OSError, ValueError):
        return ""
    return digest.hexdigest()


def load(root: pathlib.Path) -> Dict[str, Any]:
    """Read the approvals file, returning an empty structure when unusable."""
    try:
        raw = json.loads(paths.approvals_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": VERSION, "approvals": []}
    if not isinstance(raw, dict) or not isinstance(raw.get("approvals"), list):
        return {"version": VERSION, "approvals": []}
    raw.setdefault("version", VERSION)
    return raw


def find(root: pathlib.Path, relpath: str) -> Optional[Dict[str, Any]]:
    """Return the recorded approval entry for *relpath*, if any."""
    wanted = _normalize(relpath)
    for entry in load(root).get("approvals", []):
        if isinstance(entry, dict) and _normalize(entry.get("target", "")) == wanted:
            return entry
    return None


def check(root: pathlib.Path, relpath: str) -> str:
    """Return ``ok`` / ``fail`` / ``unverified`` for *relpath*.

    ``unverified`` is never rounded to either side: an unasked question is not
    a passed one, and it is not a defect either.
    """
    entry = find(root, relpath)
    if entry is None:
        return verdict.UNVERIFIED
    current = sha256_file(pathlib.Path(root) / _normalize(relpath))
    if not current:
        # Approved once, but the file is gone or unreadable now.
        return verdict.FAIL
    return verdict.OK if current == entry.get("sha256") else verdict.FAIL


def approve(
    root: pathlib.Path, relpath: str, note: str = "", by: str = "user"
) -> Dict[str, Any]:
    """Record the current hash of *relpath* as approved.

    Asks nothing: the calling command file is responsible for putting the
    question to the user (via AskUserQuestion) before invoking this. Raises
    :class:`FileNotFoundError` when the target does not exist, because
    approving a file that is not there records a meaningless hash.
    """
    key = _normalize(relpath)
    target = pathlib.Path(root) / key
    digest = sha256_file(target)
    if not digest:
        raise FileNotFoundError(f"cannot approve missing or unreadable file: {key}")

    entry = {
        "target": key,
        "sha256": digest,
        "approved_by": str(by),
        "approved_at": _now(),
        "note": str(note or ""),
    }

    data = load(root)
    kept = [
        item
        for item in data.get("approvals", [])
        if not (isinstance(item, dict) and _normalize(item.get("target", "")) == key)
    ]
    kept.append(entry)
    data["version"] = VERSION
    data["approvals"] = kept
    config.write_json_atomic(paths.approvals_file(root), data)
    return entry


def run(argv: List[str]) -> int:
    """``gatekit approve <path> [--note]`` / ``check <path>`` / ``list``."""
    import argparse  # CLI only; hooks that import approval never parse arguments

    parser = argparse.ArgumentParser(prog="gatekit approve", add_help=True)
    parser.add_argument(
        "action_or_path",
        nargs="?",
        help="'check', 'list', or a path to approve",
    )
    parser.add_argument("path", nargs="?", help="path when the action is 'check'")
    parser.add_argument("--root", default=None)
    parser.add_argument("--note", default="")
    parser.add_argument("--by", default="user")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)

    root = paths.project_root(args.root)

    if not args.action_or_path:
        parser.print_usage(sys.stderr)
        return 2

    if args.action_or_path == "list":
        for entry in load(root).get("approvals", []):
            print(f"{entry.get('target', '?')} {entry.get('sha256', '')[:12]} {entry.get('approved_at', '')}")
        return 0

    if args.action_or_path == "check":
        if not args.path:
            print("gatekit: 'check' needs a path", file=sys.stderr)
            return 2
        result = check(root, args.path)
        print(result)
        return 0 if result == verdict.OK else 1

    try:
        entry = approve(root, args.action_or_path, note=args.note, by=args.by)
    except FileNotFoundError as err:
        print(f"gatekit: {err}", file=sys.stderr)
        return 1
    print(f"approved {entry['target']} {entry['sha256'][:12]}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
