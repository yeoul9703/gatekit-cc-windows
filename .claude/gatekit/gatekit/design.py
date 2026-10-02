"""Design as data: `spec/tokens.json` v2, presets, and blast radius (ADR-0008).

Design reaches a worker through code, not through a task author's memory. This
module is the one place that reads `spec/tokens.json`, so `spec validate`,
`jobs.build_prompt` and the token gate can never disagree about its shape.

Two top-level keys are reserved. ``source`` is a list, because a design now has
several origins, and ``patterns`` holds the ``P<n>`` rows as machine data so
nothing has to parse Markdown. Every other top-level key mapping to an object
is a **token group**: `radius`, `shadow`, `breakpoint` and `motion` need no
code change here.

Version 1 files (no ``version``, or ``version: 1``, with ``source`` a string)
keep working: :func:`load_tokens` upgrades them **in memory** only, so reading
a file never rewrites it. The next write upgrades it on disk.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Any, Dict, List, Optional

from gatekit import config, paths

VERSION = 2

#: Top-level keys that are not token groups.
RESERVED_KEYS = ("version", "source", "patterns")

#: A screen or pattern id as it appears in prose: `S1`, `P12`. Bounded on both
#: sides so `SUBS1TUTE` and `PS12` are not references.
_ID_RE = re.compile(r"(?<![A-Za-z0-9])(?P<id>[SP][0-9]+)(?![A-Za-z0-9])")


def tokens_file(root) -> pathlib.Path:
    return paths.spec_dir(root) / "tokens.json"


def _read_json(path: pathlib.Path) -> Optional[Dict[str, Any]]:
    """Parse *path* as a JSON object, or ``None`` when it cannot be."""
    try:
        parsed = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return *raw* as a v2 dict, upgrading a v1 shape in memory.

    A v1 file has no ``version`` (or ``version: 1``) and a string ``source``.
    Upgrading wraps that string in a list and starts ``patterns`` empty. The
    token groups are carried through untouched, whatever they are called.
    """
    source = raw.get("source")
    if isinstance(source, str):
        source = [source] if source.strip() else []
    elif not isinstance(source, list):
        source = []
    patterns = raw.get("patterns")
    if not isinstance(patterns, list):
        patterns = []
    # Reserved keys first, so a written file reads version, origins, patterns,
    # then groups, whatever order it arrived in.
    data: Dict[str, Any] = {"version": VERSION, "source": source, "patterns": patterns}
    for key, value in raw.items():
        if key not in RESERVED_KEYS:
            data[key] = value
    return data


def load_tokens(root) -> Dict[str, Any]:
    """The project's tokens as a normalized v2 dict, or ``{}``.

    ``{}`` covers absent, unreadable, unparsable and non-object files alike:
    every caller treats all four the same way, by leaving design out.
    """
    raw = _read_json(tokens_file(root))
    if raw is None:
        return {}
    return normalize(raw)


def token_groups(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The token groups of *data*: every non-reserved key mapping to an object."""
    return {
        key: value
        for key, value in data.items()
        if key not in RESERVED_KEYS and isinstance(value, dict)
    }


# --------------------------------------------------------------- preset merge


def preset_file(name: str) -> pathlib.Path:
    return paths.skill_dir("shared") / "assets" / "presets" / "design" / ("%s.json" % name)


def _merge_token(preset_value: Any, name: str) -> Dict[str, Any]:
    """A token the preset contributes, always carrying its origin.

    A scalar is upgraded to ``{"value": ..., "evidence": "preset:<name>"}``. An
    object keeps its own keys but its evidence is overwritten: for this project
    the preset is where the value came from, whatever the preset says.
    """
    evidence = "preset:%s" % name
    if isinstance(preset_value, dict):
        merged = dict(preset_value)
        merged["evidence"] = evidence
        return merged
    return {"value": preset_value, "evidence": evidence}


def merge_preset(root, name: str) -> Dict[str, Any]:
    """Merge preset *name* into ``spec/tokens.json`` and return the result.

    Project values win, the preset fills gaps. Raises :class:`FileNotFoundError`
    when the preset does not exist and :class:`ValueError` when it is not a
    JSON object, because merging a file we could not read would silently do
    nothing.
    """
    source_path = preset_file(name)
    if not source_path.is_file():
        raise FileNotFoundError("no design preset named '%s' at %s" % (name, source_path))
    preset = _read_json(source_path)
    if preset is None:
        raise ValueError("design preset '%s' is not a JSON object: %s" % (name, source_path))

    existing = _read_json(tokens_file(root))
    data = normalize(existing) if existing is not None else normalize({})

    for group, tokens in token_groups(preset).items():
        target = data.get(group)
        if not isinstance(target, dict):
            target = {}
        for token_name, value in tokens.items():
            if token_name not in target:
                target[token_name] = _merge_token(value, name)
        data[group] = target

    known = {
        row.get("id")
        for row in data["patterns"]
        if isinstance(row, dict)
    }
    for row in preset.get("patterns") or []:
        if not isinstance(row, dict) or row.get("id") in known:
            continue
        added = dict(row)
        added["evidence"] = "preset:%s" % name
        data["patterns"].append(added)
        known.add(added.get("id"))

    marker = "preset:%s" % name
    if marker not in data["source"]:
        data["source"].append(marker)

    config.write_json_atomic(tokens_file(root), data)
    return data


# -------------------------------------------------------------- blast radius


def _task_text(task: Dict[str, Any]) -> str:
    """Everything in a task that can name a design id: title, instruction, gates."""
    parts = [str(task.get("title", "")), str(task.get("instruction", ""))]
    for gate in task.get("gates") or []:
        if isinstance(gate, dict):
            parts.extend(str(a) for a in (gate.get("argv") or []))
    return "\n".join(parts)


def _sort_key(ref: str):
    """`P2` before `P10` before `S1`: kind first, then numeric order."""
    return (ref[0], int(ref[1:]))


def normalize_id(ref: str) -> str:
    """Canonical spelling of one id: the letter plus the number, unpadded.

    `S01` and `S1` name the same screen. Keeping both spellings split the
    impact report into two entries for one screen, and since they sort to the
    same position the split landed in arbitrary order.
    """
    return "%s%d" % (ref[0].upper(), int(ref[1:]))


def referenced_ids(text: str) -> List[str]:
    """Every `S<n>` / `P<n>` in *text*, normalized, deduplicated and ordered."""
    found = {normalize_id(match.group("id")) for match in _ID_RE.finditer(text or "")}
    return sorted(found, key=_sort_key)


def impact(root) -> Dict[str, Any]:
    """Tasks that name a design id, and the ids that name them.

    This is decision 7: mid-build, the design command reports blast radius
    instead of editing `04-tasks.md`. Deciding what to redelegate stays with
    the user.
    """
    from gatekit import spec as spec_mod

    source = paths.spec_dir(root) / "04-tasks.md"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return {"tasks": [], "by_id": {}}

    rows: List[Dict[str, Any]] = []
    by_id: Dict[str, List[str]] = {}
    for task in spec_mod.parse_fences(text, "gatekit-task"):
        refs = referenced_ids(_task_text(task))
        if not refs:
            continue
        task_id = str(task.get("id", "?"))
        rows.append({"id": task_id, "refs": refs})
        for ref in refs:
            by_id.setdefault(ref, []).append(task_id)
    return {"tasks": rows, "by_id": by_id}


# ----------------------------------------------------------------------- CLI


def _render_impact(report: Dict[str, Any]) -> str:
    rows = report["tasks"]
    if not rows:
        return "design impact — no task in spec/04-tasks.md names a screen or pattern id"
    lines = ["design impact — %d task(s) reference a design id" % len(rows)]
    for ref in sorted(report["by_id"], key=_sort_key):
        lines.append("  %-6s %s" % (ref, ", ".join(report["by_id"][ref])))
    lines.append("")
    lines.append("Redelegate these tasks if the design they name changed.")
    return "\n".join(lines)


def run(argv: List[str]) -> int:
    """``gatekit design merge-preset <name>`` / ``gatekit design impact``."""
    parser = argparse.ArgumentParser(prog="gatekit design", add_help=True)
    sub = parser.add_subparsers(dest="cmd")

    p_merge = sub.add_parser("merge-preset", help="Merge a shipped preset into spec/tokens.json.")
    p_merge.add_argument("name", help="preset file name without .json")
    p_merge.add_argument("--root", default=None)

    p_impact = sub.add_parser("impact", help="List tasks that name a screen or pattern id.")
    p_impact.add_argument("--json", action="store_true", dest="as_json")
    p_impact.add_argument("--root", default=None)

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)

    if not args.cmd:
        parser.print_usage(sys.stderr)
        return 2

    root = paths.project_root(args.root)

    if args.cmd == "merge-preset":
        try:
            data = merge_preset(root, args.name)
        except (FileNotFoundError, ValueError) as err:
            print("gatekit: %s" % err, file=sys.stderr)
            return 1
        groups = token_groups(data)
        print(
            "merged preset:%s -> %s (%d group(s), %d pattern(s))"
            % (args.name, tokens_file(root), len(groups), len(data["patterns"]))
        )
        return 0

    report = impact(root)
    if args.as_json:
        print(json.dumps({"tasks": report["tasks"]}, indent=2, ensure_ascii=False))
    else:
        print(_render_impact(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
