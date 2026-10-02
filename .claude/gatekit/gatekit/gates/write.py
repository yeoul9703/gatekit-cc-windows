"""PreToolUse gate for Write / Edit / MultiEdit / NotebookEdit.

Two independent rules, either of which can deny a write:

**(a) spec before code.** While ``enforce_spec_before_code`` is on and a
``spec/`` directory exists, code stays locked until a human has approved
``spec/05-gate.md`` (a hash-anchored approval, see :mod:`gatekit.approval`).
Documentation and the spec set itself stay writable throughout, otherwise there
would be no way to produce the spec that unlocks the gate.

**(b) task write scope.** When ``GATEKIT_TASK_ID`` is set — which happens only
inside a worker session spawned by :mod:`gatekit.jobs` — the write must fall
inside that task's declared ``write_scope``. This is what stops two parallel
workers from editing each other's files. Rule (b) is deliberately stricter than
rule (a): a scoped worker gets no documentation allowlist, because a worker
assigned ``src/auth/**`` has no business rewriting the PRD.

**Paths are compared without regard to case** (ADR-0022). The kit is
Windows-only and the file system is case-insensitive: ``SRC/Auth/x.ts`` and
``src/auth/x.ts`` are one file, so they get one verdict. The fold is applied to
both sides of every comparison in this module (:func:`matches`,
:func:`in_allowlist`) — the allowlist and a task scope alike — so no spelling
of a path reaches a rule its lower-case spelling would not reach.

Denial reasons are written in the session's ``output_lang``.
"""
from __future__ import annotations

import fnmatch
import json
import os
import pathlib
from typing import Any, Dict, List, Optional

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import approval, config, hookio, ledger, paths  # noqa: E402

#: Paths that stay writable under rule (a) so the spec can be authored at all.
SPEC_ALLOWLIST = (
    "spec/**",
    ".gatekit/**",
    "docs/**",
    "README*",
    "*.md",  # root-level markdown only; the pattern is matched without '/'
)

GATE_TARGET = "spec/05-gate.md"

_MESSAGES = {
    "en": {
        "spec_first": (
            "gatekit: writing code is blocked until spec/05-gate.md is approved "
            "(current status: {status}). Run the /gatekit-gate pipeline and have "
            "the user approve the gate, or write to spec/, docs/ or *.md first. "
            "Blocked path: {path}"
        ),
        "scope": (
            "gatekit: task '{task}' may only write within {scope}. "
            "Blocked path: {path}"
        ),
        "scope_read_only": (
            "gatekit: task '{task}' is read-only and must not write any file. "
            "Blocked path: {path}"
        ),
        "scope_missing": (
            "gatekit: no write_scope found for task '{task}' (job '{job}'), so "
            "every write is refused. Blocked path: {path}"
        ),
        "outside_root": (
            "gatekit: task '{task}' may not write outside the project root. "
            "Blocked path: {path}"
        ),
    },
    "ko": {
        "spec_first": (
            "gatekit: spec/05-gate.md 승인 전에는 코드를 쓸 수 없습니다 "
            "(현재 상태: {status}). /gatekit-gate 파이프라인을 실행해 사용자 승인을 "
            "받거나, 먼저 spec/·docs/·*.md 에 작성하세요. 차단된 경로: {path}"
        ),
        "scope": (
            "gatekit: '{task}' 작업은 {scope} 범위 안에서만 쓸 수 있습니다. "
            "차단된 경로: {path}"
        ),
        "scope_read_only": (
            "gatekit: '{task}' 작업은 읽기 전용이므로 파일을 쓸 수 없습니다. "
            "차단된 경로: {path}"
        ),
        "scope_missing": (
            "gatekit: '{task}' 작업(job '{job}')의 write_scope 를 찾을 수 없어 "
            "모든 쓰기를 거부합니다. 차단된 경로: {path}"
        ),
        "outside_root": (
            "gatekit: '{task}' 작업은 프로젝트 루트 밖에 쓸 수 없습니다. "
            "차단된 경로: {path}"
        ),
    },
}


def _message(lang: str, key: str, **fields: Any) -> str:
    table = _MESSAGES.get(lang, _MESSAGES["en"])
    return table.get(key, _MESSAGES["en"][key]).format(**fields)


def target_path(tool_input: Dict[str, Any]) -> str:
    """Extract the path a write tool is about to touch.

    ``NotebookEdit`` uses ``notebook_path``; the other three use ``file_path``.
    """
    if not isinstance(tool_input, dict):
        return ""
    for key in ("file_path", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def relative_target(root: pathlib.Path, raw_path: str) -> Optional[str]:
    """Normalize *raw_path* to a POSIX path relative to *root*.

    Returns ``None`` when the target lies outside the project root. Relative
    inputs are resolved against the root, and symlinks are resolved so a link
    cannot be used to land outside the project.
    """
    candidate = pathlib.Path(raw_path)
    if not candidate.is_absolute():
        candidate = pathlib.Path(root) / candidate
    return paths.relative_to_root(root, candidate)


def fold(text: str) -> str:
    """The form in which paths and patterns are compared: lower case.

    Done explicitly instead of through ``fnmatch.fnmatch`` (which folds only
    on a Windows interpreter), so the verdict does not depend on where the
    code runs.
    """
    return text.lower()


def matches(relpath: str, pattern: str) -> bool:
    """Glob match with ``**`` crossing directory separators.

    ``fnmatch`` alone treats ``*`` as crossing ``/``, which would make
    ``src/auth/*.ts`` match a nested file. This translates the pattern so that
    ``*`` stays within one path segment while ``**`` spans any number.

    Case is ignored on both sides (:func:`fold`): the path and the pattern
    name files on a case-insensitive file system.

    A bracket is a letter, not a character set: ``src/app/[id]/page.tsx`` names
    the folder ``[id]`` (the route folders of Next.js and its kin), and reading
    it as "one of i, d" refused that very file while allowing ``src/app/i/``.
    """
    relpath = fold(relpath)
    pattern = fold(pattern.strip().replace("\\", "/"))
    while pattern.startswith("./"):
        pattern = pattern[2:]
    if not pattern:
        return False

    # A bare "**" or a "dir/**" prefix should also match the directory itself.
    if pattern.endswith("/**") and relpath == pattern[:-3]:
        return True
    if pattern == "**":
        return True

    return _glob_match(relpath.split("/"), pattern.split("/"))


def _glob_match(parts: List[str], pats: List[str]) -> bool:
    """Segment-wise match where a ``**`` segment consumes any number of parts."""
    if not pats:
        return not parts
    head, rest = pats[0], pats[1:]
    if head == "**":
        if not rest:
            return True
        for index in range(len(parts) + 1):
            if _glob_match(parts[index:], rest):
                return True
        return False
    if not parts:
        return False
    if not fnmatch.fnmatchcase(parts[0], head.replace("[", "[[]")):
        return False
    return _glob_match(parts[1:], rest)


def in_allowlist(relpath: str) -> bool:
    """True when *relpath* is writable regardless of the spec gate.

    Case-insensitive like :func:`matches`: ``SPEC/x.md``, ``Docs/a.md`` and
    ``readme.MD`` are the same files as their usual spellings.
    """
    relpath = fold(relpath)
    for pattern in SPEC_ALLOWLIST:
        if pattern == "*.md":
            # Root-level markdown only: no separator left in the path.
            if "/" not in relpath and fnmatch.fnmatchcase(relpath, "*.md"):
                return True
            continue
        if pattern == "README*":
            if "/" not in relpath and fnmatch.fnmatchcase(relpath, fold("README*")):
                return True
            continue
        if matches(relpath, pattern):
            return True
    return False


def load_task_scope(root: pathlib.Path, job_id: str, task_id: str):
    """Read ``write_scope`` from the task's ``task.json``.

    Returns the scope (a list of globs or the string ``read-only``), or ``None``
    when the task file is missing or unreadable. ``None`` means deny: a worker
    claiming a task id whose scope cannot be established gets no write access.
    """
    task_file = (
        paths.jobs_dir(root) / str(job_id) / "tasks" / str(task_id) / "task.json"
    )
    try:
        data = json.loads(task_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    scope = data.get("write_scope")
    if isinstance(scope, str):
        return scope
    if isinstance(scope, list):
        return [str(item) for item in scope]
    return None


def restrictions_active(root: pathlib.Path) -> bool:
    """True when at least one of the two rules can currently deny a write.

    Lets a caller that must parse its input (the Bash gate) skip the parse
    entirely when nothing could be denied anyway.
    """
    if os.environ.get("GATEKIT_TASK_ID"):
        return True
    cfg = config.load(root)
    if not cfg.get("enforce_spec_before_code", True):
        return False
    if not paths.spec_dir(root).is_dir():
        return False
    return approval.check(root, GATE_TARGET) != "ok"


def decide_path(root: pathlib.Path, raw_path: str, lang: str) -> Optional[Dict[str, Any]]:
    """Apply rules (b) then (a) to one target path.

    Returns a deny payload, or ``None`` to allow. Shared by the Write gate and
    the Bash gate so a shell redirect is judged exactly like a Write call.
    """
    relpath = relative_target(root, raw_path)

    # -- rule (b): task write scope, checked first because it is stricter ----
    task_id = os.environ.get("GATEKIT_TASK_ID")
    if task_id:
        job_id = os.environ.get("GATEKIT_JOB_ID", "")
        if relpath is None:
            return hookio.deny(
                _message(lang, "outside_root", task=task_id, path=raw_path)
            )
        scope = load_task_scope(root, job_id, task_id)
        if scope is None:
            return hookio.deny(
                _message(lang, "scope_missing", task=task_id, job=job_id, path=relpath)
            )
        if isinstance(scope, str):  # "read-only"
            return hookio.deny(
                _message(lang, "scope_read_only", task=task_id, path=relpath)
            )
        if not any(matches(relpath, pattern) for pattern in scope):
            return hookio.deny(
                _message(
                    lang, "scope", task=task_id, scope=", ".join(scope), path=relpath
                )
            )
        return hookio.allow()

    # -- rule (a): spec before code ----------------------------------------
    cfg = config.load(root)
    if not cfg.get("enforce_spec_before_code", True):
        return hookio.allow()
    if not paths.spec_dir(root).is_dir():
        return hookio.allow()
    if relpath is not None and in_allowlist(relpath):
        return hookio.allow()

    status = approval.check(root, GATE_TARGET)
    if status == "ok":
        return hookio.allow()

    return hookio.deny(
        _message(lang, "spec_first", status=status, path=relpath or raw_path)
    )


def session_lang(root: pathlib.Path, event: Dict[str, Any]) -> str:
    """Read the session's output language, defaulting to Korean."""
    try:
        return ledger.Ledger.load(root, hookio.session_id(event)).output_lang
    except Exception:  # noqa: BLE001 - language must never break the gate
        return "ko"


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Decide whether this write may proceed."""
    root = hookio.event_root(event)
    tool_input = event.get("tool_input") or {}

    raw_path = target_path(tool_input)
    if not raw_path:
        return hookio.allow()
    return decide_path(root, raw_path, session_lang(root, event))


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()
