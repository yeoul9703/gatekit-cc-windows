"""Worker jobs (§10).

`jobs start` builds `.gatekit/jobs/<job_id>/`, writes one directory per task,
spawns the configured worker backend with the task prompt on stdin, then runs
the task's gates. A worker that exits 0 but fails a gate is `failed`, never
`passed` — the worker's own report never decides the verdict.

Every JSON write goes through `write_json` (tmp file + `os.replace`) so a job
directory read concurrently never sees a half-written file.
"""
from __future__ import annotations

import contextlib
import datetime
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Optional

from gatekit import config, jobstore, paths, spec, verdict, workers

#: States after which a task will not change again on its own. Defined once in
#: jobstore (spec.py reads the same list); see there for every state a task has.
TERMINAL_STATES = jobstore.TERMINAL_STATES
#: Terminal states that mean "not done" for the job verdict. `blocked` is not
#: here: a task that never ran was not judged, and the job verdict reports it
#: as `unverified`, never `fail` (the cardinal rule).
NOT_DONE_STATES = ("failed", "timeout", "stopped")

GATE_TIMEOUT_S = 60.0

#: ADR-0013 decision 1. Who implements a task.
#:
#: ``host``   — the session running `/gatekit:build` writes the code itself.
#:              A worker is a *cold* session of the same model; spawning one
#:              per task pays a fresh project discovery each time and buys a
#:              second opinion from the model that is already here.
#: ``worker`` — spawn the configured backend per task, as before. Correct when
#:              the model must differ (adversarial verification) or when a
#:              round is wide enough that real parallelism beats the spawn
#:              cost.
EXECUTION_MODES = ("host", "worker")
DEFAULT_EXECUTION = "host"
#: A round with at least this many independent tasks is worth spawning for even
#: under `host`: they run at once instead of one after another.
HOST_PARALLEL_HANDOFF = 3

#: ADR-0009 decision 1. A failing gate is a broken *command* only when the
#: shell or interpreter itself reports that something the gate's argv names
#: could not be run: the pattern must match AND the matching line must
#: mention one of the gate's own arguments. A test that merely prints "No such
#: file" about a fixture does not name the argv and is expected pre-work
#: failure. Misses are safe: the job starts with a warning.
COMMAND_ERROR_PATTERNS = (
    re.compile(r"Cannot find module", re.IGNORECASE),
    re.compile(r"can't open file", re.IGNORECASE),
    re.compile(r"No such file or directory", re.IGNORECASE),
    re.compile(r"command not found", re.IGNORECASE),
    re.compile(r"\bis a directory\b", re.IGNORECASE),
    re.compile(r"not recognized as an internal or external command", re.IGNORECASE),
)
#: Exit codes the shell reserves for "could not execute": 126 (not executable),
#: 127 (not found). These are command errors on their own.
COMMAND_ERROR_EXITS = (126, 127)
#: Signals that make preflight *suspicious* (job starts, warning printed):
#: exit ≥ 2 from a runner that documents 1 as "tests failed", a usage banner
#: at the top of stderr, or a pattern above that does not name an argument.
SUSPICIOUS_MIN_EXIT = 2
#: `jobs stop` signals a recorded pid only when the live process's age agrees
#: with the recorded spawn time within this many seconds (recycled-pid guard).
STOP_PID_AGE_TOLERANCE_S = 10.0
#: Seconds `jobs stop` waits after SIGTERM before SIGKILL.
STOP_GRACE_S = 5.0
STOP_MARKER = "stop.json"
#: Exit code by which a task gate reports `unverified`: it ran, but it could not
#: judge (ADR-0008 decision 5 — the token gate uses it when tokens.json is
#: absent or the task wrote no file it knows how to scan). 0 is `ok`, every
#: other non-zero code is `fail`.
GATE_UNVERIFIED_EXIT = 3
TAIL_BYTES = 4000
#: How much failed-gate output `redelegate` appends to the next prompt.
REDELEGATE_TAIL_CHARS = 2000


# --------------------------------------------------------------------- helpers


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_job_id() -> str:
    """UTC timestamp + 4 hex chars, sortable and collision-resistant."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "%s-%s" % (stamp, secrets.token_hex(2))


def write_json(path, data) -> None:
    """Atomic JSON write: temp file in the same directory, then os.replace."""
    path = str(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        paths.replace_file(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path, default=None):
    try:
        with open(str(path), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def _tail(text: str, limit: int = TAIL_BYTES) -> str:
    return text if len(text) <= limit else text[-limit:]


def jobs_dir(root):
    return paths.state_dir(root) / "jobs"


job_dir = jobstore.job_dir
latest_job_id = jobstore.latest_job_id


def load_tasks(root) -> list:
    """Parse ```gatekit-task fences out of spec/04-tasks.md."""
    src = paths.spec_dir(root) / "04-tasks.md"
    if not src.is_file():
        return []
    return spec.parse_fences(src.read_text(encoding="utf-8"), "gatekit-task")


# ------------------------------------------------------------------- prompt


def _pattern_applies(pattern: dict, task_text: str) -> bool:
    """True when *pattern* governs a task whose words are *task_text*.

    ``applies_to: "all"`` always applies. A list applies when the task names one
    of its screen ids. Ids are compared on their canonical spelling, so `S01`
    matches `S1` while `S12` still does not drag in a pattern scoped to `S1`.
    """
    from gatekit import design as design_mod

    applies_to = pattern.get("applies_to")
    if isinstance(applies_to, str):
        return applies_to.strip().lower() == "all"
    if not isinstance(applies_to, list):
        return False
    # Compare on the canonical spelling so `S01` in applies_to still matches a
    # task that writes `S1`, and neither matches `S10`.
    mentioned = set(design_mod.referenced_ids(task_text))
    for screen in applies_to:
        if not isinstance(screen, str) or not screen.strip():
            continue
        try:
            wanted = design_mod.normalize_id(screen.strip())
        except (ValueError, IndexError):
            # Not an `S<n>`-shaped id; fall back to a literal bounded match.
            if re.search(
                r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(screen.strip()), task_text
            ):
                return True
            continue
        if wanted in mentioned:
            return True
    return False


def _applies_to_text(pattern: dict) -> str:
    applies_to = pattern.get("applies_to")
    if isinstance(applies_to, list):
        return ", ".join(str(s) for s in applies_to)
    return str(applies_to)


def _token_lines(prefix: str, value) -> list:
    """Render one token as ``<prefix>: <value>`` lines.

    A dict carrying a ``value`` key is one token that knows where it came from,
    which is the shape ``design merge-preset`` writes. Only its value reaches
    the worker: ``evidence`` is bookkeeping for the spec reader, and rendering
    it as ``color.primary.evidence`` would read like a second usable token.
    A dict without ``value`` is a genuinely nested group and still recurses.
    """
    if isinstance(value, dict):
        if "value" in value:
            return ["%s: %s" % (prefix, value["value"])]
        lines = []
        for key, child in value.items():
            lines.extend(_token_lines("%s.%s" % (prefix, key), child))
        return lines
    return ["%s: %s" % (prefix, value)]


def has_design(tokens: dict) -> bool:
    """True when *tokens* carries anything a worker could act on.

    A parsable file is not the same as a design. ``{}`` and a file holding only
    ``version``/``source`` normalize to a truthy dict but say nothing, so the
    prompt must stay byte-identical to the one with no file at all.
    """
    from gatekit import design as design_mod

    if any(entries for entries in design_mod.token_groups(tokens).values()):
        return True
    return bool(tokens.get("patterns"))


def _design_lines(task: dict, tokens: dict) -> list:
    """The ``## Design`` section body, generated from tokens.json by code.

    ADR-0008 decision 4: a pattern reaches the worker through the same brief as
    its instruction, so nothing depends on the task author having remembered to
    write "follow P2" into the text.
    """
    from gatekit import design as design_mod

    task_text = "\n".join(
        [str(task.get("title", "")), str(task.get("instruction", ""))]
    )
    lines = []
    for pattern in tokens.get("patterns") or []:
        if not isinstance(pattern, dict) or not _pattern_applies(pattern, task_text):
            continue
        lines.append(
            "- %s: %s (applies to %s)"
            % (pattern.get("id", "P?"), str(pattern.get("rule", "")).strip(), _applies_to_text(pattern))
        )

    token_lines = []
    for group, entries in sorted(design_mod.token_groups(tokens).items()):
        for name, value in entries.items():
            token_lines.extend(_token_lines("%s.%s" % (group, name), value))
    if token_lines:
        if lines:
            lines.append("")
        lines.extend(token_lines)

    if lines:
        lines.append("")
    lines.append(
        "Read spec/02-design.md and spec/02-screens.md for anything not listed here."
    )
    return lines


#: A per-screen heading in `spec/02-screens.md`: `### S2 — 플레이` / `### S2 - Play`.
_SCREEN_HEADING_RE = re.compile(r"^###\s+(?P<id>[Ss]\d+)\b\s*[—\-–:]?\s*(?P<name>.*)$")
#: A fenced block opens and closes with three or more backticks or tildes. A
#: screen spec draws flow diagrams in these, and their contents are pictures of
#: markdown, not markdown: a `### S9` inside one names no screen and a `|` line
#: inside one is not a state row.
_FENCE_RE = re.compile(r"^\s*(?P<mark>`{3,}|~{3,})")
#: Longest a single copied layout paragraph or state row may be before it is
#: cut. Spec prose has no natural bound, unlike the `name: value` token lines
#: beside it, and an unbounded paragraph would become an unusable worker stdin.
SCREEN_TEXT_MAX_CHARS = 1200
#: Longest the whole `## Screens` block may be. A task naming a dozen screens
#: must not crowd out its own instruction.
SCREENS_BLOCK_MAX_CHARS = 8000


def _clip(text: str, limit: int = SCREEN_TEXT_MAX_CHARS) -> str:
    """*text*, cut to *limit* with an ellipsis so the cut is visible."""
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def _split_row(line: str) -> list:
    """Table cells, honouring ``\\|`` as a literal pipe inside a cell.

    A naive ``split("|")`` truncates any state description containing an
    escaped pipe ("press A \\| B"), which is silent data loss in the one place
    this feature exists to be faithful.
    """
    cells, current, index = [], [], 0
    while index < len(line):
        char = line[index]
        if char == "\\" and index + 1 < len(line) and line[index + 1] == "|":
            current.append("|")
            index += 2
            continue
        if char == "|":
            cells.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    cells.append("".join(current))
    # A well-formed row opens and closes with a pipe, so drop the empty ends.
    if cells and not cells[0].strip():
        cells.pop(0)
    if cells and not cells[-1].strip():
        cells.pop()
    return [c.strip() for c in cells]


def parse_screens(text: str) -> dict:
    """``{canonical id: {"name", "layout", "states"}}`` from `02-screens.md`.

    ADR-0011 decision 3. The per-screen sections of the screen spec are
    regular: a `### S<n> — <name>` heading, a prose layout line, then a state
    table. Only those three things are taken; the screen list and flow tables
    at the top of the file repeat what the sections already say.

    Parsing is forgiving by design — a file that does not match returns the
    screens it could read and nothing else. A missing block is a prompt that
    reads as it did before this ADR, never a failed job.
    """
    from gatekit import design as design_mod

    screens: dict = {}
    current = None
    fence = None  # the marker that opened the block we are inside, or None
    for line in (text or "").splitlines():
        marker = _FENCE_RE.match(line)
        if marker:
            mark = marker.group("mark")
            if fence is None:
                fence = mark[0]
                continue
            if mark[0] == fence:  # a closing fence of the same kind
                fence = None
                continue
        if fence is not None:
            # Inside a fence every line is a picture of markdown, not markdown:
            # a `### S9` names no screen and a `|` line is not a state row.
            continue
        heading = _SCREEN_HEADING_RE.match(line)
        if heading:
            try:
                screen_id = design_mod.normalize_id(heading.group("id"))
            except (ValueError, IndexError):
                current = None
                continue
            current = {"name": heading.group("name").strip(), "layout": "", "states": []}
            screens[screen_id] = current
            continue
        if current is None:
            continue
        if line.startswith("## "):  # left the per-screen sections entirely
            current = None
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|"):
            cells = _split_row(stripped)
            # separator rows (|---|---|) carry no content
            if cells and not all(set(c) <= set("-: ") for c in cells):
                current["states"].append(cells)
            continue
        if not current["layout"] and not stripped.startswith(">"):
            current["layout"] = stripped
    return screens


def _screen_lines(task: dict, screens: dict) -> list:
    """The ``## Screens`` body: the screens this task names, or ``[]``.

    Matched by the same `S<n>` scan `_pattern_applies` uses, so a task that
    names no screen carries no block and a task that names several carries
    each. A named screen the spec does not describe is skipped rather than
    reported: the task file and the screen spec disagreeing is a spec problem,
    not something to raise inside a worker's brief.

    Copied prose is bounded twice — per paragraph and per block — because spec
    text, unlike the `name: value` token lines beside it, has no natural limit
    and an unbounded paragraph would become an unusable worker stdin.
    """
    from gatekit import design as design_mod

    task_text = "\n".join([str(task.get("title", "")), str(task.get("instruction", ""))])
    wanted = [s for s in design_mod.referenced_ids(task_text) if s in screens]
    lines, budget = [], SCREENS_BLOCK_MAX_CHARS
    for screen_id in wanted:
        if budget <= 0:
            lines.append(
                "(%d more screen(s) omitted for length — read spec/02-screens.md)"
                % (len(wanted) - len([l for l in lines if l.startswith("### ")]))
            )
            break
        screen = screens[screen_id]
        heading = "### %s" % screen_id
        if screen.get("name"):
            heading += " — %s" % _clip(screen["name"], 200)
        lines.append(heading)
        if screen.get("layout"):
            layout = _clip(screen["layout"])
            lines.extend(["", layout])
            budget -= len(layout)
        states = screen.get("states") or []
        if len(states) > 1:  # a header row plus at least one state
            lines.append("")
            for row in states[1:]:
                row_text = _clip(": ".join(row[:2]))
                lines.append("- %s" % row_text)
                budget -= len(row_text)
        lines.append("")
    return lines


def _screens_for(task: dict, root) -> list:
    """`_screen_lines` for the project's screen spec; ``[]`` when unreadable."""
    try:
        text = (pathlib.Path(str(root)) / "spec" / "02-screens.md").read_text(
            encoding="utf-8", errors="replace"
        )
    except OSError:
        return []
    try:
        return _screen_lines(task, parse_screens(text))
    except Exception:
        # A malformed screen spec must never cost a job; the brief simply
        # reads as it did before ADR-0011.
        return []


def build_prompt(task: dict, job_id: str, extra: str = "", root=None) -> str:
    """The self-contained brief handed to the worker on stdin.

    *root* is optional so existing callers keep working: without it, and
    whenever ``spec/tokens.json`` is absent or unparsable, the prompt is
    byte-identical to the one this function produced before ADR-0008.
    """
    scope = task.get("write_scope")
    if isinstance(scope, list):
        scope_text = "\n".join("- %s" % s for s in scope) or "- (none)"
    else:
        scope_text = "- %s" % (scope or "read-only")

    gates = task.get("gates") or []
    if gates:
        gate_text = "\n".join(
            "- %s: %s" % (g.get("name", "gate-%d" % i), " ".join(g.get("argv") or []))
            for i, g in enumerate(gates)
        )
    else:
        gate_text = "- (none declared)"

    parts = [
        "# Task %s — %s" % (task.get("id", "?"), task.get("title", "")),
        "",
        "job: %s" % job_id,
        "",
        "## Instruction",
        "",
        str(task.get("instruction", "")).strip(),
        "",
        "## Write scope",
        "",
        "You may create or modify ONLY these paths. Writes outside this scope are",
        "denied by a hook, not by convention.",
        "",
        scope_text,
        "",
        "## Gates that will judge this task",
        "",
        "These commands run after you exit. They decide whether the task passed.",
        "",
        gate_text,
        "",
    ]

    if root is not None:
        from gatekit import design as design_mod

        tokens = design_mod.load_tokens(root)
        if has_design(tokens):
            parts += ["## Design", ""] + _design_lines(task, tokens) + [""]
        # ADR-0011 decision 3: the screen spec is pushed into the brief, not
        # pointed at, so a correction the owner made at preview time reaches
        # the worker as text.
        screen_lines = _screens_for(task, root)
        if screen_lines:
            parts += ["## Screens", ""] + screen_lines

    parts += [
        "## Reporting",
        "",
        "When you are done, reply with a short report: what you changed and what",
        "you could not do. Do not claim success; the gates decide.",
    ]
    if extra:
        parts += ["", "## Previous attempt failed", "", extra.strip()]
    return "\n".join(parts) + "\n"


# --------------------------------------------------------------- task running


def _task_dir(jdir, task_id: str):
    return jdir / "tasks" / task_id


def _set_status(jdir, task_id: str, **fields) -> dict:
    path = _task_dir(jdir, task_id) / "status.json"
    status = read_json(path, {}) or {}
    status.update(fields)
    status["task_id"] = task_id
    status["updated_at"] = _now()
    write_json(path, status)
    return status


def run_gates(root, task: dict) -> dict:
    """Run every gate of a task sequentially. Returns the gates.json payload."""
    results = []
    for index, gate in enumerate(task.get("gates") or []):
        name = gate.get("name") or "gate-%d" % index
        argv = gate.get("argv")
        if not isinstance(argv, list) or not argv:
            results.append(
                {
                    "name": name,
                    "verdict": verdict.FAIL,
                    "exit": None,
                    "detail": "gate has no argv",
                    "stdout_tail": "",
                    "stderr_tail": "",
                }
            )
            continue
        started = time.time()
        try:
            proc = subprocess.run(
                paths.resolve_argv(argv),
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=GATE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "name": name,
                    "verdict": verdict.UNVERIFIED,
                    "exit": None,
                    "detail": "timed out after %ds" % int(GATE_TIMEOUT_S),
                    "elapsed_s": round(time.time() - started, 3),
                    "stdout_tail": "",
                    "stderr_tail": "",
                }
            )
            continue
        except OSError as exc:
            results.append(
                {
                    "name": name,
                    "verdict": verdict.FAIL,
                    "exit": None,
                    "detail": "could not run: %s" % exc,
                    "elapsed_s": round(time.time() - started, 3),
                    "stdout_tail": "",
                    "stderr_tail": "",
                }
            )
            continue
        out = (proc.stdout or b"").decode("utf-8", "replace")
        err = (proc.stderr or b"").decode("utf-8", "replace")
        if proc.returncode == 0:
            gate_verdict, detail = verdict.OK, "exit 0"
        elif proc.returncode == GATE_UNVERIFIED_EXIT:
            # A gate that could not judge says so by exit code rather than by
            # guessing. `unverified` is never rounded to either side, so this
            # task neither passes nor fails on it.
            gate_verdict, detail = verdict.UNVERIFIED, "exit %d (unverified)" % GATE_UNVERIFIED_EXIT
        else:
            gate_verdict, detail = verdict.FAIL, "exit %d" % proc.returncode
        results.append(
            {
                "name": name,
                "verdict": gate_verdict,
                "exit": proc.returncode,
                "detail": detail,
                "elapsed_s": round(time.time() - started, 3),
                "stdout_tail": _tail(out),
                "stderr_tail": _tail(err),
            }
        )
    aggregate = verdict.aggregate([r["verdict"] for r in results]) if results else verdict.UNVERIFIED
    passed = sum(1 for r in results if r["verdict"] == verdict.OK)
    return {
        "verdict": aggregate,
        "passed": passed,
        "total": len(results),
        "gates": results,
        "ran_at": _now(),
    }


def _argv_tokens(argv) -> list:
    """Strings a command-error line would name: each argument and its basename."""
    tokens = []
    for arg in (argv or [])[1:] if isinstance(argv, list) else []:
        s = str(arg).strip()
        if not s or s.startswith("-"):
            continue
        tokens.append(s)
        base = os.path.basename(s.rstrip("/"))
        if base and base != s:
            tokens.append(base)
    return tokens


def classify_gate_result(gate: dict, argv=None) -> str:
    """ADR-0009 decision 1: `command_error`, `suspicious`, or `expected`.

    `command_error` — refuse the job — only when the failing gate's exit code
    is one of `COMMAND_ERROR_EXITS`, or a `COMMAND_ERROR_PATTERNS` line also
    names one of the gate's own arguments (the interpreter could not run what
    the fence points at), or a `command not found` line names argv[0].
    `suspicious` — start the job, print a warning — for exit ≥ 2, a pattern
    that names nothing from argv, or a usage banner opening stderr.
    `expected` — start the job silently — for everything else, and always for
    `ok` and `unverified` verdicts or a malformed result.
    """
    if not isinstance(gate, dict) or gate.get("verdict") != verdict.FAIL:
        return "expected"
    code = gate.get("exit")
    if isinstance(code, int) and code in COMMAND_ERROR_EXITS:
        return "command_error"
    stdout = gate.get("stdout_tail") or ""
    stderr = gate.get("stderr_tail") or ""
    tokens = _argv_tokens(argv)
    program = os.path.basename(str(argv[0])) if isinstance(argv, list) and argv else ""
    matched_without_name = False
    for line in (stdout + "\n" + stderr).splitlines():
        if not any(p.search(line) for p in COMMAND_ERROR_PATTERNS):
            continue
        if "command not found" in line.lower():
            if program and program in line:
                return "command_error"
            matched_without_name = True
            continue
        if any(tok in line for tok in tokens):
            return "command_error"
        matched_without_name = True
    if matched_without_name:
        return "suspicious"
    if isinstance(code, int) and code >= SUSPICIOUS_MIN_EXIT:
        return "suspicious"
    first = stderr.lstrip().lower()
    if first.startswith("usage:"):
        return "suspicious"
    return "expected"


def looks_like_command_error(gate: dict, argv=None) -> bool:
    """True only when `classify_gate_result` says `command_error`."""
    return classify_gate_result(gate, argv) == "command_error"


class GatePreflightError(ValueError):
    """ADR-0009: a task gate is a broken command; the job was not started."""


def _scope_has_files(root, task: dict) -> bool:
    """Does anything already exist under the task's write_scope globs?"""
    scope = task.get("write_scope")
    if not isinstance(scope, list):
        return True  # read-only or malformed: not our call
    root = pathlib.Path(root)
    for pattern in scope:
        try:
            if any(p.is_file() for p in root.glob(str(pattern))):
                return True
        except (OSError, ValueError):
            continue
    return False


def preflight(root, jdir, tasks: list) -> dict:
    """ADR-0009 decision 1: run every task's gates once before any worker.

    Writes `tasks/<id>/preflight.json`. Returns
    `{"passed": [ids], "warnings": [str]}`. Raises `GatePreflightError` when a
    gate is a broken command, before any worker has been spawned.
    """
    passed, warnings, broken = [], [], []
    for task in tasks:
        task_id = str(task.get("id"))
        result = run_gates(root, task)
        write_json(_task_dir(jdir, task_id) / "preflight.json", result)
        gates = result.get("gates") or []
        if result.get("total", 0) > 0 and result.get("verdict") == verdict.OK:
            detail = "gates passed at preflight; no worker spawned"
            if not _scope_has_files(root, task):
                note = ("warn: gate passed before any work existed in the write scope "
                        "— check that it can fail")
                warnings.append("%s: %s" % (task_id, note))
                detail += "; " + note
            _set_status(jdir, task_id, state="passed", exit=None,
                        gates_verdict=result["verdict"], gates_passed=result["passed"],
                        gates_total=result["total"], finished_at=_now(), detail=detail)
            passed.append(task_id)
            continue
        declared = {str(g.get("name") or "gate-%d" % i): g.get("argv")
                    for i, g in enumerate(task.get("gates") or [])}
        for gate in gates:
            kind = classify_gate_result(gate, declared.get(str(gate.get("name"))))
            if kind == "command_error":
                tail = _tail((gate.get("stderr_tail") or gate.get("stdout_tail") or ""), 400)
                broken.append("task %s gate `%s` (%s): %s" % (
                    task_id, gate.get("name"), gate.get("detail", ""), tail.strip()))
            elif kind == "suspicious":
                warnings.append(
                    "%s: gate `%s` failed at preflight (%s) in a way that may be the "
                    "command rather than the work; starting anyway — check it if the "
                    "task fails" % (task_id, gate.get("name"), gate.get("detail", "")))
    if broken:
        raise GatePreflightError(
            "gate preflight refused to start the job — the command itself fails, "
            "no worker could make it pass:\n" + "\n".join(broken)
        )
    return {"passed": passed, "warnings": warnings}


def _spawn_worker(root, backend: dict, task: dict, job_id: str, tdir, timeout_s: float,
                  on_spawn=None) -> dict:
    """Run the worker for one task; returns {"exit", "timed_out"}."""
    # A worker gets exactly the two gatekit variables it needs; nothing a
    # parent worker or evaluator session exported leaks into it.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
    env["GATEKIT_TASK_ID"] = str(task.get("id", ""))
    env["GATEKIT_JOB_ID"] = job_id
    prompt = (tdir / "prompt.md").read_text(encoding="utf-8")

    out_path, err_path = tdir / "output.txt", tdir / "stderr.txt"
    started = time.time()
    with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
        try:
            proc = subprocess.Popen(
                paths.resolve_argv(backend["argv"]),
                cwd=str(root),
                env=env,
                stdin=subprocess.PIPE,
                stdout=out_f,
                stderr=err_f,
            )
        except OSError as exc:
            err_f.write(("gatekit: could not spawn worker: %s\n" % exc).encode("utf-8"))
            return {"exit": None, "timed_out": False, "spawn_error": str(exc),
                    "elapsed_s": round(time.time() - started, 3)}
        if on_spawn is not None:
            try:
                # A `jobs stop` that landed between the "running" status and
                # this pid being recorded found no pid to signal; on_spawn
                # reports it so the freshly spawned worker is not left running.
                if on_spawn(proc.pid, started):
                    proc.kill()
            except Exception:  # recording the pid must never break the run
                pass
        try:
            proc.communicate(prompt.encode("utf-8"), timeout=timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            if _IS_WINDOWS:
                # `claude.cmd`-style shims: end the whole tree, not just cmd.exe.
                _terminate_pid(proc.pid)
            proc.kill()
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
            timed_out = True
    return {
        "exit": proc.returncode,
        "timed_out": timed_out,
        "elapsed_s": round(time.time() - started, 3),
    }


def execute_task(root, jdir, job_id: str, task: dict, backend: dict, timeout_s: float) -> dict:
    """Spawn worker, then gates. Returns the final status dict."""
    task_id = str(task.get("id"))
    tdir = _task_dir(jdir, task_id)
    _set_status(jdir, task_id, state="running", started_at=_now())

    def record_pid(pid, started):
        _set_status(jdir, task_id, pid=int(pid), pid_started_at=float(started))
        return _stop_requested(jdir)

    result = _spawn_worker(root, backend, task, job_id, tdir, timeout_s, on_spawn=record_pid)
    # The worker has been reaped; its pid may be reused by anything now, so
    # `jobs stop` must never signal it again.
    _set_status(jdir, task_id, pid=None)

    if _stop_requested(jdir):
        # ADR-0009 decision 3: `jobs stop` ended this worker; whatever exit code
        # the signal produced is not a verdict on the work.
        return _set_status(jdir, task_id, state="stopped", exit=result.get("exit"),
                           elapsed_s=result.get("elapsed_s"), finished_at=_now(),
                           detail="stopped by jobs stop")

    if result["timed_out"]:
        return _set_status(
            jdir,
            task_id,
            state="timeout",
            exit=None,
            elapsed_s=result.get("elapsed_s"),
            finished_at=_now(),
            detail="worker exceeded task_timeout_s=%s and was killed" % timeout_s,
        )

    _set_status(jdir, task_id, state="gating", exit=result["exit"],
                elapsed_s=result.get("elapsed_s"))
    gates = run_gates(root, task)
    write_json(tdir / "gates.json", gates)

    worker_ok = result["exit"] == 0
    all_gates_ok = gates["total"] > 0 and gates["verdict"] == verdict.OK
    state = "passed" if (worker_ok and all_gates_ok) else "failed"
    if not worker_ok:
        detail = "worker exited %s" % result["exit"]
    elif not all_gates_ok:
        detail = "worker exited 0 but gates verdict is %s (%d/%d ok)" % (
            gates["verdict"], gates["passed"], gates["total"],
        )
    else:
        detail = "worker exited 0 and %d/%d gates ok" % (gates["passed"], gates["total"])

    # ADR-0014: the count follows the task across jobs.
    record_attempt(root, task_id, state, job_id=job_id,
                   gate=_first_failing_gate(gates))
    return _set_status(
        jdir,
        task_id,
        state=state,
        exit=result["exit"],
        gates_verdict=gates["verdict"],
        gates_passed=gates["passed"],
        gates_total=gates["total"],
        finished_at=_now(),
        detail=detail,
    )


# ------------------------------------------------------------------ evaluate

EVALUATOR_BRIEF = """# Evaluator brief

You are the evaluator. You did not write this code and you must not change it.
Your session is read-only: the CLI sandbox and the write gate both refuse
writes, and any attempt to write is itself a finding against you.

1. Run `{launcher} contract run --json` from the project root.
2. Read `spec/05-gate.md` and carry out every E2E step it describes by hand,
   in order. Record what you actually observed, not what should happen.
3. For each criterion and each E2E step give one verdict from
   `ok / warn / fail / unverified`. A step you could not run is `unverified`;
   never round it to either side.
4. Do not fix anything you find. Report it.
5. Reply with the verdict table only — one row per criterion and per E2E step,
   then the aggregate — in {lang}. Do not paste command transcripts.
"""


def evaluator_brief(root, lang: str = "en") -> str:
    return EVALUATOR_BRIEF.format(launcher=paths.cli_invocation(), lang=lang)


def evaluate(root, backend_name=None, prompt_path=None, timeout_s=None, lang: str = "en",
             force_read_only_evaluator: bool = False) -> dict:
    """Run one worker as the independent evaluator.

    The backend is *backend_name* or ``verify.evaluator`` from config; ``agent``
    means the host's own subagent and is not runnable from here. The worker
    gets ``GATEKIT_TASK_ID=evaluate`` with a read-only ``task.json`` so the
    write gate refuses writes inside its session.

    Always runs the backend's read-only sandbox: the write gate is the real
    protection, and running the writable sandbox would be a code-writing
    session with nothing watching it. ``force_read_only_evaluator`` is kept
    for callers that pass it explicitly; it is a no-op today since read-only
    is already the only mode.
    """
    name = backend_name or workers.evaluator_name(root)
    if name == "agent":
        raise ValueError(
            "verify.evaluator is 'agent' (the host's own subagent); run "
            "`workers set-evaluator <backend>` or pass --backend to use a CLI evaluator"
        )

    use_read_only = True
    backend = workers.resolve(root, name, read_only=use_read_only)
    cfg = config.load(root)
    if timeout_s is None:
        timeout_s = float((cfg.get("build") or {}).get("task_timeout_s", 900))

    job_id = new_job_id()
    jdir = job_dir(root, job_id)
    edir = jdir / "evaluate"
    edir.mkdir(parents=True, exist_ok=True)
    task = {"id": "evaluate", "title": "independent evaluation", "write_scope": "read-only"}
    write_json(edir / "task.json", task)
    if prompt_path is not None:
        prompt = pathlib.Path(prompt_path).read_text(encoding="utf-8")
    else:
        prompt = evaluator_brief(root, lang)
    (edir / "prompt.md").write_text(prompt, encoding="utf-8")
    write_json(jdir / "job.json", {
        "job_id": job_id,
        "kind": "evaluate",
        "started_at": _now(),
        "backend": {"name": backend["name"], "argv": backend["argv"],
                    "unsafe": backend["unsafe"], "read_only": use_read_only},
        "timeout_s": timeout_s,
    })
    write_json(edir / "status.json", {"task_id": "evaluate", "state": "running", "started_at": _now()})

    result = _spawn_worker(root, backend, task, job_id, edir, timeout_s)
    if result["timed_out"]:
        state, detail = "timeout", "evaluator exceeded %ss and was killed" % timeout_s
    elif result["exit"] == 0:
        state, detail = "passed", "evaluator exited 0"
    else:
        state, detail = "failed", "evaluator exited %s" % result["exit"]
    status_doc = {
        "task_id": "evaluate", "state": state, "exit": result["exit"],
        "elapsed_s": result.get("elapsed_s"), "finished_at": _now(), "detail": detail,
    }
    write_json(edir / "status.json", status_doc)
    try:
        output = (edir / "output.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        output = ""
    return {"job_id": job_id, "backend": backend["name"], "state": state,
            "exit": result["exit"], "detail": detail, "output_tail": _tail(output)}


# ----------------------------------------------------------------- scheduling


def order_tasks(tasks: list) -> list:
    """Group tasks into waves honouring `round` then `depends_on`.

    Returns a list of waves; every task in a wave may run concurrently.
    A dependency cycle (or a dependency on an unknown id) leaves the remaining
    tasks in one final wave rather than dropping them.
    """
    remaining = list(tasks)
    known = {str(t.get("id")) for t in tasks}
    done = set()
    waves = []
    while remaining:
        rounds = [int(t.get("round", 1) or 1) for t in remaining]
        current_round = min(rounds)
        ready = [
            t
            for t in remaining
            if int(t.get("round", 1) or 1) == current_round
            and all(
                (str(d) in done or str(d) not in known)
                for d in (t.get("depends_on") or [])
            )
        ]
        if not ready:  # cycle or cross-round dependency: run what is left as-is
            waves.append(list(remaining))
            break
        waves.append(ready)
        for t in ready:
            done.add(str(t.get("id")))
        ready_ids = {id(t) for t in ready}
        remaining = [t for t in remaining if id(t) not in ready_ids]
    return waves


def _run_wave(root, jdir, job_id, wave, backend, timeout_s, parallel) -> None:
    """Run one wave, at most `parallel` tasks at a time.

    Tasks are run sequentially within each slot using threads; the heavy lifting
    is subprocess I/O, so threads are sufficient and keep the stdlib-only rule.
    """
    import threading

    limit = max(1, int(parallel or 1))
    lock = threading.Semaphore(limit)
    errors = []

    def worker(task):
        with lock:
            try:
                if _stop_requested(jdir):
                    _set_status(jdir, str(task.get("id")), state="stopped",
                                finished_at=_now(), detail="stopped by jobs stop")
                    return
                execute_task(root, jdir, job_id, task, backend, timeout_s)
            except BaseException as exc:  # never let one task kill the job
                errors.append((task.get("id"), exc))
                _set_status(
                    jdir,
                    str(task.get("id")),
                    state="failed",
                    finished_at=_now(),
                    detail="gatekit internal error: %s" % exc,
                )

    threads = [threading.Thread(target=worker, args=(t,)) for t in wave]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# ---------------------------------------------------------------- subcommands


def _stop_requested(jdir) -> bool:
    return (pathlib.Path(jdir) / STOP_MARKER).is_file()


def _split_wave_by_dependencies(jdir, wave: list, job_task_ids: set) -> tuple:
    """ADR-0009 decision 5: a task runs only when every in-job dependency passed.

    Returns `(runnable, waiting)`; each waiting task's status gains a detail
    naming the dependency and its state. Dependencies outside the job are not
    the job's business and never block.
    """
    runnable, waiting = [], []
    for task in wave:
        blocker = None
        for dep in task.get("depends_on") or []:
            dep = str(dep)
            if dep not in job_task_ids:
                continue
            dep_status = read_json(_task_dir(jdir, dep) / "status.json", {}) or {}
            state = str(dep_status.get("state", "queued"))
            if state != "passed":
                shown = state
                if dep_status.get("gates_verdict") == verdict.UNVERIFIED:
                    shown = "%s, gates unverified" % state
                blocker = (dep, shown)
                break
        if blocker is None:
            runnable.append(task)
        else:
            _set_status(jdir, str(task.get("id")), state="queued",
                        detail="waiting on %s (%s)" % blocker)
            waiting.append(task)
    return runnable, waiting


def _finalise_unrun(jdir, tasks: list, stopped: bool) -> None:
    """After the waves: tasks still queued are `stopped` or `blocked`."""
    for task in tasks:
        task_id = str(task.get("id"))
        st = read_json(_task_dir(jdir, task_id) / "status.json", {}) or {}
        if st.get("state", "queued") != "queued":
            continue
        if stopped:
            _set_status(jdir, task_id, state="stopped", finished_at=_now(),
                        detail="stopped by jobs stop")
            continue
        # Re-read the dependency's *final* state: the "waiting on" detail was
        # frozen mid-run and a cascade (a → b → c) would name b as `queued`
        # when it actually ended `blocked`.
        dep = "a dependency"
        for candidate in task.get("depends_on") or []:
            dep_status = read_json(_task_dir(jdir, str(candidate)) / "status.json", None)
            if not dep_status:
                continue
            state = str(dep_status.get("state", "queued"))
            if state != "passed":
                shown = state
                if dep_status.get("gates_verdict") == verdict.UNVERIFIED:
                    shown = "%s, gates unverified" % state
                dep = "%s (%s)" % (candidate, shown)
                break
        _set_status(jdir, task_id, state="blocked", finished_at=_now(),
                    detail="dependency %s ended before this task could run" % dep)


def start(root, task_ids=None, backend_name=None, parallel=None, dry_run=False,
          no_preflight=False) -> dict:
    """Create a job directory and (unless dry_run) run every selected task.

    ADR-0009: unless `no_preflight`, every task's gates run once before any
    worker is spawned (see `preflight`), and a task whose in-job dependency
    did not pass is left `blocked` rather than run.
    """
    cfg = config.load(root)
    build_cfg = cfg.get("build") or {}
    tasks = load_tasks(root)
    if task_ids:
        wanted = [t.strip() for t in task_ids if t.strip()]
        by_id = {str(t.get("id")): t for t in tasks}
        missing = [w for w in wanted if w not in by_id]
        if missing:
            raise ValueError("unknown task id(s): %s" % ", ".join(missing))
        tasks = [by_id[w] for w in wanted]
    if not tasks:
        raise ValueError(
            "no tasks found; expected ```gatekit-task fences in spec/04-tasks.md"
        )

    # ADR-0014: the budget binds here too. Starting a fresh job was how it was
    # escaped on gk-trial2 — the counter lived in status.json, which `start`
    # resets — so refusing only in `redelegate` closes half the door.
    retry_limit = int(build_cfg.get("max_retries", 2) or 0)
    exhausted = [
        str(t.get("id")) for t in tasks
        if consecutive_failures(root, str(t.get("id"))) >= retry_limit > 0
    ]
    if exhausted:
        raise RetryBudgetExceeded(
            "task(s) %s already failed %d consecutive time(s) across jobs "
            "(max_retries=%d). Read spec/RECOVERY.md and the failing gate's "
            "output, then re-run with --force-retry <task_id> once the cause "
            "is addressed." % (
                ", ".join(exhausted),
                max(consecutive_failures(root, t) for t in exhausted),
                retry_limit)
        )

    mode = execution_mode(cfg)
    if backend_name:
        # Naming a backend is an explicit request for that model to do the work.
        mode = "worker"
    backend = workers.resolve(root, backend_name)
    parallel = int(parallel or build_cfg.get("parallel", 3) or 1)
    timeout_s = float(build_cfg.get("task_timeout_s", 900) or 900)
    max_retries = int(build_cfg.get("max_retries", 2) or 0)

    job_id = new_job_id()
    jdir = job_dir(root, job_id)
    (jdir / "tasks").mkdir(parents=True, exist_ok=True)

    job = {
        "version": 1,
        "job_id": job_id,
        "started_at": _now(),
        "backend": {
            "name": backend["name"],
            "argv": backend["argv"],
            "unsafe": backend["unsafe"],
        },
        "parallel": parallel,
        "task_timeout_s": timeout_s,
        "max_retries": max_retries,
        "dry_run": bool(dry_run),
        "no_preflight": bool(no_preflight),
        "execution": mode,
        "preflight_warnings": [],
        "tasks": [str(t.get("id")) for t in tasks],
        "config": {"build": build_cfg},
    }
    write_json(jdir / "job.json", job)

    for task in tasks:
        task_id = str(task.get("id"))
        tdir = _task_dir(jdir, task_id)
        tdir.mkdir(parents=True, exist_ok=True)
        write_json(tdir / "task.json", task)
        (tdir / "prompt.md").write_text(
            build_prompt(task, job_id, root=root), encoding="utf-8"
        )
        _set_status(jdir, task_id, state="queued", attempt=1, created_at=_now())

    if dry_run:
        return job

    if not no_preflight:
        pre = preflight(root, jdir, tasks)  # raises GatePreflightError before any spawn
        job["preflight_warnings"] = pre["warnings"]
        job["preflight_passed"] = pre["passed"]
        write_json(jdir / "job.json", job)
        already = set(pre["passed"])
        tasks_to_run = [t for t in tasks if str(t.get("id")) not in already]
    else:
        tasks_to_run = list(tasks)

    if mode == "host":
        # ADR-0013 decision 1: hand the ordered plan back and stop. The session
        # that called this already knows the project; it implements each task
        # and calls `complete_task`, which runs the same gates a worker's exit
        # would have triggered. A wide round is still worth spawning for, and
        # the plan marks those rounds so the caller can hand them off.
        plan = []
        for index, wave in enumerate(order_tasks(tasks_to_run), start=1):
            for task in wave:
                plan.append({
                    "id": str(task.get("id")),
                    "round": index,
                    "parallel_candidate": len(wave) >= HOST_PARALLEL_HANDOFF,
                })
            for task in wave:
                _set_status(jdir, str(task.get("id")), state="queued",
                            detail="awaiting the host session (build.execution=host)")
        job["plan"] = plan
        write_json(jdir / "job.json", job)
        return job

    job_task_ids = {str(t.get("id")) for t in tasks}
    waiting_all = []
    for wave in order_tasks(tasks_to_run):
        if _stop_requested(jdir):
            break
        runnable, waiting = _split_wave_by_dependencies(jdir, wave, job_task_ids)
        waiting_all.extend(waiting)
        if runnable:
            _run_wave(root, jdir, job_id, runnable, backend, timeout_s, parallel)

    _finalise_unrun(jdir, tasks_to_run, stopped=_stop_requested(jdir))
    return _finalise_job(jdir, job)


# --------------------------------------------------- attempts (ADR-0014)

#: Per-task consecutive-failure counts, beside config.json. The count lives
#: with the **task** because that is what an operator retries: `status.json`
#: resets to `attempt=1` on every `jobs start`, so a task that failed eight
#: times across ten jobs never reached `max_retries` even once (gk-trial2).
ATTEMPTS_FILE = "attempts.json"
#: States that count as a judged failure of the work. `blocked` and `stopped`
#: are neither — one never ran, the other was ended by the operator.
ATTEMPT_FAILURE_STATES = ("failed", "timeout")


def _first_failing_gate(gates: dict) -> str:
    """Name of the first gate that did not pass, for the ledger's record."""
    for gate in (gates or {}).get("gates") or []:
        if isinstance(gate, dict) and gate.get("verdict") != verdict.OK:
            return str(gate.get("name", ""))
    return ""


def _attempts_path(root):
    return paths.state_dir(root) / ATTEMPTS_FILE


def read_attempts(root) -> dict:
    """The attempt ledger; an absent or corrupt file reads as empty."""
    data = read_json(_attempts_path(root), None)
    if not isinstance(data, dict):
        return {"version": 1, "tasks": {}}
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        data["tasks"] = {}
    return data


def consecutive_failures(root, task_id: str) -> int:
    entry = (read_attempts(root).get("tasks") or {}).get(str(task_id))
    if not isinstance(entry, dict):
        return 0
    try:
        return int(entry.get("failures", 0) or 0)
    except (TypeError, ValueError):
        return 0


def record_attempt(root, task_id: str, state: str, job_id: str = "",
                   gate: str = "") -> int:
    """Fold one terminal outcome into the task's count; returns the new total.

    A `passed` clears the entry: the run converged, and what matters is whether
    a task is *currently* looping. Anything that is not a judgement of the work
    leaves the count alone.
    """
    task_id = str(task_id)
    data = read_attempts(root)
    tasks = data.setdefault("tasks", {})
    entry: dict = tasks.get(task_id)
    if not isinstance(entry, dict):
        entry = {"failures": 0}

    if state == "passed":
        entry = {"failures": 0}
    elif state in ATTEMPT_FAILURE_STATES:
        try:
            entry["failures"] = int(entry.get("failures", 0) or 0) + 1
        except (TypeError, ValueError):
            entry["failures"] = 1
        entry["last_job"] = str(job_id)
        entry["last_gate"] = str(gate)
    else:
        return consecutive_failures(root, task_id)

    entry["updated_at"] = _now()
    tasks[task_id] = entry
    data["version"] = 1
    write_json(_attempts_path(root), data)
    return int(entry.get("failures", 0) or 0)


def clear_attempts(root, task_id: str) -> None:
    """Forget one task's failures — `--force-retry`, the operator saying they
    changed something. Per task, never global."""
    data = read_attempts(root)
    if str(task_id) in (data.get("tasks") or {}):
        del data["tasks"][str(task_id)]
        write_json(_attempts_path(root), data)


def _dependency_evidence(task: dict, dependency: dict) -> bool:
    """True when *task*'s own words refer to something *dependency* writes.

    ADR-0013 decision 4. A `depends_on` is justified by need, not by reading
    order: "X comes earlier in the feature list" is not a dependency. Evidence
    is the dependency's id, or the basename of a path in its write scope,
    appearing in this task's title or instruction.

    This is authoring guidance, so the test errs toward *finding* evidence: a
    reported dependency is a prompt to look, never a refusal.
    """
    text = "%s %s" % (task.get("title", ""), task.get("instruction", ""))
    needles = [str(dependency.get("id", "")).strip()]
    scope = dependency.get("write_scope")
    globs = [scope] if isinstance(scope, str) else list(scope or [])
    for glob in globs:
        if not isinstance(glob, str):
            continue
        # Only the leaf names a dependency actually owns count. A shared
        # ancestor like `src` is not evidence of anything — every task in the
        # project sits under it.
        parts = [p for p in glob.replace("\\", "/").split("/") if p]
        leaf = ""
        for part in reversed(parts):
            if part not in ("**", "*") and not part.startswith("*"):
                leaf = part
                break
        if leaf and len(parts) > 1:
            needles.append(leaf)
        elif leaf and len(parts) == 1:
            needles.append(leaf)   # a top-level file, e.g. package.json
    for needle in needles:
        if not needle:
            continue
        # Bounded match: a short id like `a` or a name like `db` must not be
        # found inside an unrelated word. `\b` is wrong for identifiers holding
        # `.` or `-`, so the boundary is "not an identifier character".
        if re.search(r"(?<![0-9A-Za-z_.\-])%s(?![0-9A-Za-z_.\-])" % re.escape(needle),
                     text):
            return True
    return False


def _dependency_depth(task_id: str, by_id: dict, unevidenced_pairs=(), _seen=()) -> int:
    """Longest chain of *evidenced* dependencies behind *task_id*.

    A cycle stops the walk rather than recursing; the shape report is advisory
    and must not hang on a malformed task file.
    """
    if task_id in _seen or task_id not in by_id:
        return 0
    depths = [
        1 + _dependency_depth(str(dep), by_id, unevidenced_pairs, _seen + (task_id,))
        for dep in (by_id[task_id].get("depends_on") or [])
        if str(dep) in by_id and (task_id, str(dep)) not in unevidenced_pairs
    ]
    return max(depths) if depths else 0


def shape(root, task_ids=None) -> dict:
    """How the task file would run: counts, waves, and unevidenced links.

    `/gatekit:tasks` shows this before writing `spec/04-tasks.md`, because
    rounds are what cost time and nothing today makes them visible. On the
    gk-trial2 run nine tasks — a reasonable count — were spread over seven
    rounds, five holding a single task, and every pair at the same dependency
    depth had disjoint write scopes: the serialisation was declared, not
    required.
    """
    tasks = load_tasks(root)
    if task_ids:
        wanted = {t.strip() for t in task_ids if t.strip()}
        tasks = [t for t in tasks if str(t.get("id")) in wanted]
    if not tasks:
        raise ValueError(
            "no tasks found; expected ```gatekit-task fences in spec/04-tasks.md"
        )

    by_id = {str(t.get("id")): t for t in tasks}
    waves = [[str(t.get("id")) for t in wave] for wave in order_tasks(tasks)]

    unevidenced = []
    for task_id, task in by_id.items():
        for dep in task.get("depends_on") or []:
            dependency = by_id.get(str(dep))
            if dependency and not _dependency_evidence(task, dependency):
                unevidenced.append([task_id, str(dep)])
    unevidenced.sort()

    # What the plan would look like with only the evidenced links kept. The
    # declared `round` is dropped here on purpose: it is a consequence of the
    # dependencies the author wrote, so keeping it would hide the very saving
    # this number exists to show.
    pruned = []
    for task in tasks:
        copy = dict(task)
        copy["depends_on"] = [
            d for d in (task.get("depends_on") or [])
            if [str(task.get("id")), str(d)] not in unevidenced
        ]
        copy["round"] = 1 + _dependency_depth(
            str(task.get("id")), by_id, unevidenced_pairs=set(map(tuple, unevidenced))
        )
        pruned.append(copy)

    return {
        "tasks": len(tasks),
        "rounds": len(waves),
        "waves": waves,
        "serial": len(tasks),
        "unevidenced": unevidenced,
        "rounds_if_pruned": len(order_tasks(pruned)),
    }


def execution_mode(cfg: dict) -> str:
    """``build.execution`` — ``host`` or ``worker`` (ADR-0013 decision 1).

    An unset value means ``host``. An unrecognised one also means ``host``
    rather than an error: the field decides who types, and a typo must not
    stop a build.
    """
    value = str(((cfg.get("build") or {}).get("execution") or DEFAULT_EXECUTION)).strip()
    return value if value in EXECUTION_MODES else DEFAULT_EXECUTION


def complete_task(root, task_id: str, job_id: Optional[str] = None) -> dict:
    """Run a host-implemented task's gates and record the verdict.

    The counterpart of `execute_task` for `build.execution = "host"`: the
    session wrote the code itself, so there is no worker exit code to weigh —
    the gates alone decide, exactly as they do when a worker exits 0. Same
    `gates.json`, same `status.json`, same words.
    """
    job_id = job_id or latest_job_id(root)
    if not job_id:
        raise ValueError("no job under .gatekit/jobs/; run `jobs start` first")
    jdir = job_dir(root, job_id)
    job = read_json(jdir / "job.json", None)
    if not job:
        raise ValueError("job %s has no job.json" % job_id)
    if task_id not in (job.get("tasks") or []):
        raise ValueError("task %r is not in job %s" % (task_id, job_id))

    task = read_json(_task_dir(jdir, task_id) / "task.json", None)
    if not task:
        raise ValueError("task %r has no task.json in job %s" % (task_id, job_id))

    gates = run_gates(root, task)
    write_json(_task_dir(jdir, task_id) / "gates.json", gates)
    passed = gates["total"] > 0 and gates["verdict"] == verdict.OK
    # A host attempt is an attempt: it must count exactly as a worker's does.
    record_attempt(root, task_id, "passed" if passed else "failed",
                   job_id=job_id, gate=_first_failing_gate(gates))
    return _set_status(
        jdir,
        task_id,
        state="passed" if passed else "failed",
        exit=0,
        gates_verdict=gates["verdict"],
        gates_passed=gates["passed"],
        gates_total=gates["total"],
        finished_at=_now(),
        detail="implemented by the host session; %d/%d gates %s"
        % (gates["passed"], gates["total"], gates["verdict"]),
    )


def recheck(root, task_ids=None, job_id: Optional[str] = None) -> dict:
    """Re-run a task's gates against the working tree. No worker, no new job.

    ADR-0013 decision 3. A gate names test files and commands that do not exist
    until the work is done, so refining one mid-build is normal — on the
    gk-trial2 run 28 of 35 worker spawns existed only because a gate moved
    while the code was already correct. The right response to a moved gate is
    to run it, which takes seconds; re-deriving the code takes minutes.

    Gates are read from the **current** `spec/04-tasks.md`, not from the job's
    snapshot, since the point is to pick up the edit. Verdicts are recorded
    exactly as `execute_task` records them, `unverified` included — a gate that
    could not judge still does not round to a pass.
    """
    job_id = job_id or latest_job_id(root)
    if not job_id:
        raise ValueError("no job to recheck under .gatekit/jobs/")
    jdir = job_dir(root, job_id)
    job = read_json(jdir / "job.json", None)
    if not job:
        raise ValueError("job %s has no job.json" % job_id)

    current = {str(t.get("id")): t for t in load_tasks(root)}
    wanted = list(task_ids) if task_ids else list(job.get("tasks") or [])
    rechecked, missing = [], []
    for task_id in wanted:
        task = current.get(task_id)
        if task is None:
            # The task file no longer describes this task; say so rather than
            # silently leaving a stale status behind.
            missing.append(task_id)
            continue
        gates = run_gates(root, task)
        write_json(_task_dir(jdir, task_id) / "gates.json", gates)
        passed = gates["total"] > 0 and gates["verdict"] == verdict.OK
        _set_status(
            jdir,
            task_id,
            state="passed" if passed else "failed",
            gates_verdict=gates["verdict"],
            gates_passed=gates["passed"],
            gates_total=gates["total"],
            finished_at=_now(),
            detail="recheck: %d/%d gates %s (no worker)"
            % (gates["passed"], gates["total"], gates["verdict"]),
        )
        rechecked.append(task_id)
    return {"job_id": job_id, "rechecked": rechecked, "missing": missing}


def _merge_job_json(jdir, fields: dict, fallback: Optional[dict] = None) -> dict:
    """Re-read `job.json`, apply *fields*, write it back.

    `jobs stop` and the draining runner both finish a job, and either may hold
    a copy read before the other wrote. Re-reading immediately before the
    write keeps `stopped_at` and `finished_at` from erasing each other; the
    write itself is atomic, so the surviving loser is a lost field, never a
    corrupt file.
    """
    with _job_json_lock(jdir):
        job = read_json(jdir / "job.json", None)
        if not isinstance(job, dict):
            job = dict(fallback or {})
        job.update(fields)
        write_json(jdir / "job.json", job)
    return job


@contextlib.contextmanager
def _job_json_lock(jdir, wait_s: float = 5.0, stale_s: float = 30.0):
    """Cross-process mutex around a `job.json` read-modify-write.

    Re-reading right before the write narrows the lost-update window between
    `jobs stop` and the draining runner but does not close it (they are
    separate processes, and the runner reacts to the worker being killed within
    milliseconds). `os.mkdir` is atomic on every platform, so a lock directory
    serialises them. A lock older than *stale_s* is a crashed holder's and is
    broken; if the lock cannot be taken within *wait_s* the write proceeds
    unlocked rather than hanging a hook or a stop.
    """
    lock = str(jdir / "job.json.lock")
    held = False
    deadline = time.time() + wait_s
    while True:
        try:
            os.mkdir(lock)
            held = True
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > stale_s:
                    os.rmdir(lock)
                    continue
            except OSError:
                pass
            if time.time() >= deadline:
                break
            time.sleep(0.01)
        except OSError:
            break
    try:
        yield
    finally:
        if held:
            try:
                os.rmdir(lock)
            except OSError:
                pass


def _finalise_job(jdir, job: dict) -> dict:
    """Stamp `finished_at` without disturbing a concurrent `stopped_at`."""
    return _merge_job_json(jdir, {"finished_at": _now()}, job)


def status(root, job_id: Optional[str] = None) -> dict:
    job_id = job_id or latest_job_id(root)
    if not job_id:
        return {"job_id": None, "verdict": verdict.UNVERIFIED, "tasks": [],
                "detail": "no jobs under .gatekit/jobs/"}
    jdir = job_dir(root, job_id)
    job = read_json(jdir / "job.json", {}) or {}
    rows = []
    for task_id in job.get("tasks", []):
        st = read_json(_task_dir(jdir, task_id) / "status.json", {}) or {}
        # ADR-0014: the count carried across jobs, so a task on its first
        # attempt in *this* job but its sixth overall does not look fresh.
        carried = consecutive_failures(root, task_id)
        rows.append(
            {
                "id": task_id,
                "state": st.get("state", "queued"),
                "attempt": st.get("attempt", 1),
                "consecutive_failures": carried,
                "gates_passed": st.get("gates_passed", 0),
                "gates_total": st.get("gates_total", 0),
                "detail": st.get("detail", ""),
            }
        )
    states = [r["state"] for r in rows]
    if not rows:
        overall = verdict.UNVERIFIED
    elif any(s in NOT_DONE_STATES for s in states):
        overall = verdict.FAIL
    elif any(s in ("queued", "running", "gating", "blocked") for s in states):
        # `blocked` never ran and was never judged: unverified, not fail.
        overall = verdict.UNVERIFIED
    else:
        overall = verdict.OK
    done = all(s in TERMINAL_STATES for s in states) if states else False
    finished_at = job.get("finished_at")
    # ADR-0013 host execution: `start()` returns the plan and spawns nothing,
    # so nothing else ever calls `_finalise_job`. A worker-mode job stamps
    # `finished_at` when its own loop drains; a host-mode job only becomes
    # done when `complete_task` records the last terminal state, and this is
    # the first place that moment is visible. Found on a real retrial where
    # every task passed but the job never recorded when.
    if done and not finished_at:
        finished_at = _finalise_job(jdir, job).get("finished_at")
    return {
        "job_id": job_id,
        "verdict": overall,
        "backend": (job.get("backend") or {}).get("name"),
        "started_at": job.get("started_at"),
        "finished_at": finished_at,
        "stopped_at": job.get("stopped_at"),
        "preflight_warnings": job.get("preflight_warnings") or [],
        "done": done,
        "tasks": rows,
    }


def _process_age_s(pid: int) -> Optional[float]:
    """Seconds since `pid` started; None when unknown.

    POSIX: `ps -o etime=`. Windows has no `ps`, so the creation time comes
    from GetProcessTimes.
    """
    if _IS_WINDOWS:
        return _windows_process_age_s(pid)
    try:
        out = subprocess.run(["ps", "-o", "etime=", "-p", str(pid)],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=5).stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return _parse_etime(out)


_IS_WINDOWS = os.name == "nt"
_WIN_QUERY_LIMITED = 0x1000          # PROCESS_QUERY_LIMITED_INFORMATION
_WIN_STILL_ACTIVE = 259
#: 100-ns FILETIME ticks between 1601-01-01 and the Unix epoch.
_WIN_EPOCH_DELTA_S = 11644473600


def _windows_open(pid: int):
    """(kernel32, handle) for a query-only handle to `pid`; handle is 0 when
    the process does not exist or cannot be opened."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel32, kernel32.OpenProcess(_WIN_QUERY_LIMITED, False, int(pid))


def _windows_process_age_s(pid: int) -> Optional[float]:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32, handle = _windows_open(pid)
        if not handle:
            return None
        try:
            created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
            if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                            ctypes.byref(kernel), ctypes.byref(user)):
                return None
            ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        finally:
            kernel32.CloseHandle(handle)
        return max(0.0, time.time() - (ticks / 1e7 - _WIN_EPOCH_DELTA_S))
    except Exception:  # unknown age must degrade to "do not touch the pid"
        return None


def _pid_alive(pid: int) -> bool:
    """True when a process with this pid exists and has not exited.

    Never use `os.kill(pid, 0)` for this on Windows: there every signal other
    than CTRL_*_EVENT is TerminateProcess, so a "probe" would kill the worker.
    """
    if _IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes

            kernel32, handle = _windows_open(pid)
            if not handle:
                return False
            try:
                code = wintypes.DWORD()
                kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return False
                return code.value == _WIN_STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def _parse_etime(text: str) -> Optional[float]:
    """Parse `ps -o etime=` output, `[[dd-]hh:]mm:ss`, into seconds; None if odd."""
    rest = (text or "").strip()
    if not rest:
        return None
    days = 0
    if "-" in rest:
        d, rest = rest.split("-", 1)
        try:
            days = int(d)
        except ValueError:
            return None
    try:
        nums = [int(p) for p in rest.split(":")]
    except ValueError:
        return None
    if len(nums) == 3:
        h, m, s = nums
    elif len(nums) == 2:
        h, (m, s) = 0, nums
    else:
        return None
    return float(days * 86400 + h * 3600 + m * 60 + s)


def _pid_belongs_to_status(pid: int, pid_started_at: float) -> bool:
    """True only when a live process of that pid is as old as the recorded spawn."""
    if not _pid_alive(pid):
        return False
    age = _process_age_s(pid)
    if age is None:
        return False
    expected = time.time() - float(pid_started_at)
    return abs(age - expected) <= STOP_PID_AGE_TOLERANCE_S


def _terminate_pid(pid: int, grace_s: Optional[float] = None) -> bool:
    """SIGTERM, wait up to `grace_s`, then SIGKILL. True when a signal was sent.

    Windows has neither signal: `os.kill(pid, SIGTERM)` is an immediate
    TerminateProcess, and there is no SIGKILL. There the worker's whole process
    tree is ended with `taskkill /T /F` (a `.cmd` shim leaves its child
    running otherwise), falling back to `os.kill`.
    """
    import signal

    if _IS_WINDOWS:
        return _terminate_pid_windows(pid, signal)
    grace = STOP_GRACE_S if grace_s is None else float(grace_s)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    deadline = time.time() + grace
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True  # gone
        time.sleep(0.05)
    try:
        # Unreachable on Windows (returned above); SIGKILL exists on POSIX only.
        os.kill(pid, signal.SIGKILL)  # pyright: ignore[reportAttributeAccessIssue]
    except OSError:
        pass
    return True


def _terminate_pid_windows(pid: int, signal_mod) -> bool:
    sent = False
    try:
        result = subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        sent = result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        pass
    if not sent:
        try:
            os.kill(pid, signal_mod.SIGTERM)  # TerminateProcess
            sent = True
        except OSError:
            return False
    deadline = time.time() + 5.0
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(0.05)
    return True


def stop(root, job_id: Optional[str] = None) -> dict:
    """ADR-0009 decision 3: end a running job.

    Writes the stop marker so the runner stops taking tasks, signals every
    recorded worker pid that is still alive *and* was started by this job
    (age check against `pid_started_at`, so a recycled pid is never touched),
    then records `stopped` on every task that was running or queued.
    """
    job_id = job_id or latest_job_id(root)
    if not job_id:
        raise ValueError("no job to stop under .gatekit/jobs/")
    jdir = job_dir(root, job_id)
    job = read_json(jdir / "job.json", None)
    if not job:
        raise ValueError("job %s has no job.json" % job_id)

    write_json(jdir / STOP_MARKER, {"requested_at": _now()})
    stopped, signalled, skipped = [], [], []
    for task_id in job.get("tasks", []):
        st = read_json(_task_dir(jdir, task_id) / "status.json", {}) or {}
        state = st.get("state", "queued")
        if state in TERMINAL_STATES:
            continue
        pid = st.get("pid")
        # Only a task still in `running` owns a live worker; `gating` has
        # already reaped it and the pid may belong to anyone by now.
        if state == "running" and isinstance(pid, int):
            if _pid_belongs_to_status(pid, st.get("pid_started_at") or 0.0) \
                    and _terminate_pid(pid):
                signalled.append(task_id)
            else:
                skipped.append(task_id)
        _set_status(jdir, task_id, state="stopped", finished_at=_now(),
                    detail="stopped by jobs stop")
        stopped.append(task_id)

    _merge_job_json(jdir, {"stopped_at": _now()}, job)
    return {"job_id": job_id, "stopped": stopped, "signalled": signalled, "skipped": skipped}


def wait(root, job_id: Optional[str] = None, timeout: float = 0.0) -> dict:
    """Poll `status` until every task is terminal or `timeout` seconds elapse."""
    deadline = time.time() + timeout if timeout and timeout > 0 else None
    while True:
        current = status(root, job_id)
        if current.get("done"):
            return current
        if deadline is not None and time.time() >= deadline:
            current["detail"] = "wait timed out after %ss" % timeout
            return current
        time.sleep(0.2)


def results(root, job_id: Optional[str] = None) -> dict:
    return status(root, job_id)


def redelegate(root, task_id: str, job_id: Optional[str] = None) -> dict:
    """Archive the failed attempt, extend the prompt with the gate output, rerun."""
    job_id = job_id or latest_job_id(root)
    if not job_id:
        raise ValueError("no job to redelegate in")
    jdir = job_dir(root, job_id)
    job = read_json(jdir / "job.json", {}) or {}
    tdir = _task_dir(jdir, task_id)
    if not tdir.is_dir():
        raise ValueError("task %r is not part of job %s" % (task_id, job_id))

    st = read_json(tdir / "status.json", {}) or {}
    attempt = int(st.get("attempt", 1) or 1)
    max_retries = int(job.get("max_retries", 2) or 0)
    # ADR-0014: whichever is further along — this job's attempts or the count
    # carried across jobs. The in-job number alone was resettable by starting
    # another job, which is how a task failed eight times under a budget of 2.
    carried = consecutive_failures(root, task_id)
    if max_retries > 0 and (attempt > max_retries or carried > max_retries):
        raise RetryBudgetExceeded(
            "task %r has failed %d consecutive time(s) across jobs "
            "(attempt %d in this job; max_retries=%d). Read spec/RECOVERY.md "
            "and the failing gate's output; once the cause is addressed, "
            "`jobs start --force-retry %s`."
            % (task_id, max(carried, attempt - 1), attempt, max_retries, task_id)
        )

    # ADR-0009 decision 2: the operator may have fixed the task since the job
    # started; re-read it from spec/04-tasks.md rather than the snapshot.
    current = {str(t.get("id")): t for t in load_tasks(root)}
    if task_id not in current:
        raise ValueError(
            "task %r is no longer in spec/04-tasks.md; put it back or start a new job"
            % task_id
        )
    snapshot = read_json(tdir / "task.json", {}) or {}
    fresh = current[task_id]
    changed = []
    if fresh.get("gates") != snapshot.get("gates"):
        changed.append("gates changed")
    if fresh.get("instruction") != snapshot.get("instruction"):
        changed.append("instruction changed")
    if fresh.get("write_scope") != snapshot.get("write_scope"):
        changed.append("write_scope changed")
    reread_note = ""
    if fresh != snapshot:
        write_json(tdir / "task.json", fresh)
        reread_note = "task re-read from spec/04-tasks.md (%s)" % (
            ", ".join(changed) or "other fields changed")

    archive = tdir / ("attempt-%d" % attempt)
    archive.mkdir(parents=True, exist_ok=True)
    for name in ("prompt.md", "output.txt", "stderr.txt", "gates.json", "status.json"):
        src = tdir / name
        if src.is_file():
            shutil.move(str(src), str(archive / name))

    gates = read_json(archive / "gates.json", {}) or {}
    failed = [
        g for g in gates.get("gates", []) if g.get("verdict") in (verdict.FAIL, verdict.UNVERIFIED)
    ]
    if failed:
        last = failed[-1]
        extra = "\n".join(
            [
                "Attempt %d failed gate `%s` (%s)." % (attempt, last.get("name"), last.get("detail", "")),
                "",
                "stdout (tail):",
                "```",
                _tail(last.get("stdout_tail", ""), REDELEGATE_TAIL_CHARS),
                "```",
                "",
                "stderr (tail):",
                "```",
                _tail(last.get("stderr_tail", ""), REDELEGATE_TAIL_CHARS),
                "```",
                "",
                "Fix the cause, stay inside the write scope, then stop.",
            ]
        )
    else:
        extra = "Attempt %d did not pass. No gate output was captured (the worker " \
                "may have exited non-zero or timed out). Re-do the task." % attempt
    # ADR-0009 decision 4: name the residual case preflight cannot catch.
    extra += (
        "\n\nIf the gate command itself looks wrong — it names a file or directory "
        "this task was never asked to create, or it fails in a way no code change "
        "could fix — do not adapt the code so that the wrong command passes. Stop, "
        "and say in your last message which gate looks wrong and why. A human will "
        "fix the task file."
    )

    task = read_json(tdir / "task.json", {}) or {}
    (tdir / "prompt.md").write_text(
        build_prompt(task, job_id, extra, root=root), encoding="utf-8"
    )
    detail = "redelegated after attempt %d" % attempt
    if reread_note:
        detail += "; " + reread_note
    _set_status(jdir, task_id, state="queued", attempt=attempt + 1, created_at=_now(),
                detail=detail)

    backend = workers.resolve(root, (job.get("backend") or {}).get("name"))
    timeout_s = float(job.get("task_timeout_s", 900) or 900)
    final = execute_task(root, jdir, job_id, task, backend, timeout_s)
    if reread_note:
        final = _set_status(jdir, task_id,
                            detail="%s; %s" % (final.get("detail", ""), reread_note))
    return final


class RetryBudgetExceeded(Exception):
    """Raised when `redelegate` is asked to exceed `build.max_retries`."""


def clean(root, all_jobs: bool = False) -> list:
    """Remove job directories. Default keeps the newest job."""
    base = jobs_dir(root)
    if not base.is_dir():
        return []
    names = sorted(p.name for p in base.iterdir() if p.is_dir())
    victims = names if all_jobs else names[:-1]
    for name in victims:
        shutil.rmtree(str(base / name), ignore_errors=True)
    return victims


# --------------------------------------------------------------------------- CLI


def _usage() -> str:
    return (
        "usage: python3 -m gatekit jobs <command>\n"
        "  start [--tasks id,id] [--backend name] [--parallel N] [--dry-run] [--no-preflight]\n"
        "  status [--job ID] [--json]\n"
        "  wait [--job ID] [--timeout S]\n"
        "  results [--job ID] [--compact|--json]\n"
        "  complete <task_id> [--job ID]\n"
        "                         run a host-implemented task's gates and record\n"
        "                         the verdict (build.execution=host, ADR-0013)\n"
        "  recheck [task_id ...] [--task a,b] [--job ID] [--json]\n"
        "                         re-run gates from the current spec/04-tasks.md;\n"
        "                         no worker, no new job (ADR-0013)\n"
        "  redelegate <task_id> [--job ID]\n"
        "  stop [--job ID]\n"
        "  evaluate [--backend name] [--prompt FILE] [--lang ko|en] [--json]\n"
        "  clean [--all]\n"
    )


def _opt(argv: list, flag: str):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def _positionals(argv: list) -> list:
    """Bare arguments, with every ``--flag`` and the value that follows removed.

    ``_opt`` reads an option's value without consuming it, so a naive
    "everything not starting with --" scan picks up `--root`'s path as if it
    were a task id.
    """
    out, skip = [], False
    for arg in argv:
        if skip:
            skip = False
            continue
        if arg.startswith("--"):
            # Value-taking flags are those `_opt` is asked for; the rest are
            # bare switches whose next argument is a real positional.
            skip = arg in ("--root", "--job", "--task", "--tasks", "--backend",
                           "--parallel", "--timeout", "--prompt", "--lang",
                           "--force-retry")
            continue
        out.append(arg)
    return out


def _print_table(payload: dict) -> None:
    print("job %s  backend=%s  verdict=%s" % (
        payload.get("job_id"), payload.get("backend"), payload.get("verdict")))
    for row in payload.get("tasks", []):
        # ADR-0014: a carried count beyond this job's own attempt is the case
        # that used to be invisible — a task freshly "attempt 1" here that has
        # actually failed several times across other jobs.
        # Any carried failure is worth a flag: even "attempt 1" in this job
        # can be a task's third loss elsewhere, and that is exactly the case
        # that was invisible before ADR-0014.
        carried = row.get("consecutive_failures", 0)
        suffix = " (%d consecutive)" % carried if carried > 0 else ""
        print("  %-24s %-12s %d/%d  %s%s" % (
            row["id"], row["state"], row["gates_passed"], row["gates_total"],
            row.get("detail", ""), suffix))


def _print_compact(payload: dict) -> None:
    for row in payload.get("tasks", []):
        print("%s %s %d/%d" % (row["id"], row["state"], row["gates_passed"], row["gates_total"]))


def run(argv: list) -> int:
    argv = list(argv)
    root = paths.project_root(_opt(argv, "--root"))
    if not argv or argv[0] in ("-h", "--help", "help"):
        sys.stdout.write(_usage())
        return 0 if argv else 1
    cmd, rest = argv[0], argv[1:]
    job_id = _opt(rest, "--job")

    try:
        if cmd == "start":
            forced = _opt(rest, "--force-retry")
            if forced:
                for task_id in forced.split(","):
                    if task_id.strip():
                        clear_attempts(root, task_id.strip())
            tasks_arg = _opt(rest, "--tasks")
            job = start(
                root,
                task_ids=tasks_arg.split(",") if tasks_arg else None,
                backend_name=_opt(rest, "--backend"),
                parallel=_opt(rest, "--parallel"),
                dry_run="--dry-run" in rest,
                no_preflight="--no-preflight" in rest,
            )
            payload = status(root, job["job_id"])
            if "--json" in rest:
                print(json.dumps(payload, indent=2))
            else:
                _print_table(payload)
                for line in payload.get("preflight_warnings") or []:
                    print("  warn: %s" % line)
            return 0 if payload["verdict"] != verdict.FAIL else 1

        if cmd == "stop":
            result = stop(root, job_id)
            print("job %s stopped — %d task(s) marked stopped, %d worker(s) signalled%s" % (
                result["job_id"], len(result["stopped"]), len(result["signalled"]),
                (", %d pid(s) skipped (not this job's process)" % len(result["skipped"]))
                if result["skipped"] else ""))
            return 0

        if cmd == "shape":
            info = shape(root, (_opt(rest, "--tasks") or "").split(",") or None
                         if _opt(rest, "--tasks") else None)
            if "--json" in rest:
                print(json.dumps(info, indent=2, ensure_ascii=False))
            else:
                print("tasks %d · rounds %d  (serial %d)" % (
                    info["tasks"], info["rounds"], info["serial"]))
                for index, wave in enumerate(info["waves"], start=1):
                    print("  round %d (%d): %s" % (index, len(wave), ", ".join(wave)))
                if info["unevidenced"]:
                    print("  %d dependency link(s) with no evidence in the "
                          "instruction; dropping them gives %d round(s):" % (
                              len(info["unevidenced"]), info["rounds_if_pruned"]))
                    for task_id, dep in info["unevidenced"]:
                        print("    %s -> %s" % (task_id, dep))
            return 0

        if cmd == "complete":
            names = _positionals(rest)
            if not names:
                print("jobs complete: missing <task_id>", file=sys.stderr)
                return 2
            st = complete_task(root, names[0], job_id)
            print("%s %s — %s" % (st.get("task_id"), st.get("state"), st.get("detail", "")))
            return 0 if st.get("state") == "passed" else 1

        if cmd == "recheck":
            names = _positionals(rest)
            tasks_arg = _opt(rest, "--task")
            if tasks_arg:
                names = tasks_arg.split(",")
            result = recheck(root, task_ids=names or None, job_id=job_id)
            payload = status(root, result["job_id"])
            if "--json" in rest:
                print(json.dumps({**result, "verdict": payload["verdict"]}, indent=2))
            else:
                _print_table(payload)
                if result["missing"]:
                    print("  warn: not in spec/04-tasks.md: %s" % ", ".join(result["missing"]))
            return 0 if payload["verdict"] != verdict.FAIL else 1

        if cmd in ("status", "results"):
            payload = status(root, job_id)
            if "--json" in rest:
                print(json.dumps(payload, indent=2))
            elif "--compact" in rest:
                _print_compact(payload)
            else:
                _print_table(payload)
            return 0 if payload["verdict"] != verdict.FAIL else 1

        if cmd == "wait":
            timeout = float(_opt(rest, "--timeout") or 0)
            payload = wait(root, job_id, timeout)
            if "--json" in rest:
                print(json.dumps(payload, indent=2))
            else:
                _print_table(payload)
            return 0 if payload["verdict"] != verdict.FAIL else 1

        if cmd == "redelegate":
            positional = _positionals(rest)
            if not positional:
                print("jobs redelegate: missing <task_id>", file=sys.stderr)
                return 2
            st = redelegate(root, positional[0], job_id)
            print("%s %s — %s" % (st.get("task_id"), st.get("state"), st.get("detail", "")))
            return 0 if st.get("state") == "passed" else 1

        if cmd == "evaluate":
            result = evaluate(
                root,
                backend_name=_opt(rest, "--backend"),
                prompt_path=_opt(rest, "--prompt"),
                lang=_opt(rest, "--lang") or "en",
                force_read_only_evaluator="--force-read-only-evaluator" in rest,
            )
            if "--json" in rest:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print("evaluate job %s  backend=%s  state=%s — %s" % (
                    result["job_id"], result["backend"], result["state"], result["detail"]))
                print("--- evaluator reply (tail) ---")
                print(result["output_tail"].rstrip("\n"))
            return 0 if result["state"] == "passed" else 1

        if cmd == "clean":
            removed = clean(root, all_jobs="--all" in rest)
            print("removed %d job dir(s)%s" % (
                len(removed), (": " + ", ".join(removed)) if removed else ""))
            return 0

    except RetryBudgetExceeded as exc:
        print("jobs: %s" % exc, file=sys.stderr)
        return 3
    except GatePreflightError as exc:
        print("jobs: %s" % exc, file=sys.stderr)
        return 4
    except ValueError as exc:
        print("jobs: %s" % exc, file=sys.stderr)
        return 2

    print("jobs: unknown command %r\n" % cmd, file=sys.stderr)
    sys.stderr.write(_usage())
    return 2
