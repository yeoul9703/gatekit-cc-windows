"""Build jobs (§10).

`jobs start` builds `.gatekit/jobs/<job_id>/`, writes one directory per task
(`task.json`, the brief `prompt.md`, `status.json`) and hands back the ordered
plan. It starts nothing: the session that runs the build implements a task
itself when it is alone in its round and hands the tasks of a wider round to
subagents, one each, with the text `jobs start` prints. Whoever implements a
task calls `jobs complete`, which runs the task's gates. A task whose gates do
not pass is `failed`, never `passed` — a report of success never decides the
verdict.

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
import time
from typing import Optional

from gatekit import config, jobstore, paths, spec, util, verdict

#: States after which a task will not change again on its own. Defined once in
#: jobstore (spec.py reads the same list); see there for every state a task has.
TERMINAL_STATES = jobstore.TERMINAL_STATES
#: Terminal states that mean "not done" for the job verdict. `blocked` is not
#: here: a task that never ran was not judged, and the job verdict reports it
#: as `unverified`, never `fail` (the cardinal rule).
NOT_DONE_STATES = ("failed", "timeout", "stopped")

GATE_TIMEOUT_S = 60.0

#: Who builds a task is this one rule, not a setting. A round with two or more
#: tasks is handed out, one subagent per task; a round with a single task is
#: done by the session that runs the build. The plan marks the tasks of a
#: handed-out round `parallel_candidate`, and `jobs start` prints the text to
#: hand each of them over with (`handoff_text`).
HOST_PARALLEL_HANDOFF = 2

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
#: Exit code by which a task gate reports `unverified`: it ran, but it could not
#: judge (ADR-0008 decision 5 — the token gate uses it when tokens.json is
#: absent or the task wrote no file it knows how to scan). 0 is `ok`, every
#: other non-zero code is `fail`.
GATE_UNVERIFIED_EXIT = 3
TAIL_BYTES = 4000


# --------------------------------------------------------------------- helpers


_now = util.now_iso


def new_job_id() -> str:
    """UTC timestamp + 4 hex chars, sortable and collision-resistant."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "%s-%s" % (stamp, secrets.token_hex(2))


#: Atomic JSON write and tolerant JSON read: one definition each, in util.
write_json = util.write_json_atomic
read_json = util.read_json


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
    the brief: ``evidence`` is bookkeeping for the spec reader, and rendering
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
    """True when *tokens* carries anything a task could be built from.

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

    ADR-0008 decision 4: a pattern reaches the task through the same brief as
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
#: beside it, and an unbounded paragraph would make the brief unusable.
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
    not something to raise inside a task's brief.

    Copied prose is bounded twice — per paragraph and per block — because spec
    text, unlike the `name: value` token lines beside it, has no natural limit
    and an unbounded paragraph would make the brief unusable.
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


def _scope_text(scope) -> str:
    """A write scope on one line: its globs, or `read-only`."""
    if isinstance(scope, list):
        return ", ".join(str(s) for s in scope) or "(none)"
    return str(scope or "read-only")


def _read_first_lines(task: dict, tasks) -> list:
    """The ``## Read first`` body: what to read before writing, and no more.

    Two sources. The task's own `read` list is written by whoever cut the
    tasks, when the most was known about the project. The paths of the tasks
    it depends on are taken from their `write_scope` in *tasks* (every task of
    the spec), so the work it builds on is named without anyone remembering to.
    Whoever takes the task reads these and does not explore further: reading
    the repository again is what a written brief is there to save.
    """
    read = task.get("read")
    files = [p.strip() for p in read if isinstance(p, str) and p.strip()] \
        if isinstance(read, list) else []
    by_id = {str(t.get("id")): t for t in (tasks or []) if isinstance(t, dict)}
    built_on = []
    for dep in task.get("depends_on") or []:
        earlier = by_id.get(str(dep))
        if earlier is not None:
            built_on.append("- %s: %s" % (dep, _scope_text(earlier.get("write_scope"))))
    if not files and not built_on:
        return ["Nothing is listed to read first. Do not explore the repository beyond",
                "your own write scope.", ""]

    lines = []
    if files:
        lines += ["Read these files before you write anything:", ""]
        lines += ["- %s" % path for path in files]
        lines.append("")
    if built_on:
        lines += ["This task builds on earlier tasks. Each line is a task id and the",
                  "paths that task wrote:", ""]
        lines += built_on
        lines.append("")
    lines += [
        "Do not explore beyond what is listed here and your own write scope. Skip a",
        "listed file that does not exist.",
        "",
    ]
    return lines


def build_prompt(task: dict, job_id: str, root=None, tasks=None) -> str:
    """The self-contained brief for one task, written to its `prompt.md`.

    Whoever implements the task, a subagent or the session itself, works from
    this file alone: the instruction, what to read first, the paths it may
    write, the gates that judge it and how to run them, what it may and may
    not do, the design and screens it names, and the one line to answer with.

    *tasks* is every task of the spec; the paths written by the tasks this one
    depends on are taken from it. *root* is optional so existing callers keep
    working: without it, and whenever ``spec/tokens.json`` is absent or
    unparsable, the prompt carries no design or screens section.
    """
    task_id = str(task.get("id", "?"))
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
        "# Task %s — %s" % (task_id, task.get("title", "")),
        "",
        "job: %s" % job_id,
        "",
        "## Instruction",
        "",
        str(task.get("instruction", "")).strip(),
        "",
        "## Read first",
        "",
    ]
    parts += _read_first_lines(task, tasks)
    parts += [
        "## Write scope",
        "",
        "You may create or modify ONLY these paths. Do not change anything outside",
        "this scope.",
        "",
        scope_text,
        "",
        "## Gates that will judge this task",
        "",
        "These commands decide whether the task passed.",
        "",
        gate_text,
        "",
        "Before you answer, run them yourself from the project root:",
        "",
        "    %s jobs complete %s --job %s" % (paths.cli_invocation(), task_id, job_id),
        "",
        "It prints `%s passed` or `%s failed`. On `failed`, fix the code and run it"
        % (task_id, task_id),
        "again until it prints `passed`. Every failed run is counted against the",
        "task: use the project's test runner while you work, and this command when",
        "you expect it to pass.",
        "",
        "## Tools",
        "",
        "You may run the project's own test runner and the `jobs complete` command",
        "above.",
        "",
        "Do not:",
        "",
        "- install a program on this computer",
        "- write outside the write scope above",
        "- edit a gate command or anything under `spec/`",
        "- edit `.gatekit/approvals.json`, `.gatekit/contract.json`, the gate code",
        "  under `.claude/`, or `.claude/settings.json`",
        "- start another agent",
        "",
    ]

    if root is not None:
        from gatekit import design as design_mod

        tokens = design_mod.load_tokens(root)
        if has_design(tokens):
            parts += ["## Design", ""] + _design_lines(task, tokens) + [""]
        # ADR-0011 decision 3: the screen spec is pushed into the brief, not
        # pointed at, so a correction the owner made at preview time reaches
        # the brief as text.
        screen_lines = _screens_for(task, root)
        if screen_lines:
            parts += ["## Screens", ""] + screen_lines

    parts += [
        "## Reporting",
        "",
        "Reply with one line and nothing else: `passed`, or `blocked: <reason>` when",
        "you could not make the gates pass. Do not keep running a gate you cannot",
        "make pass. Do not paste output.",
        "Do not claim success; the gates decide.",
    ]
    return "\n".join(parts) + "\n"


def handoff_text(job_id: str, task: dict) -> str:
    """The prompt to hand one task to a subagent with, to be passed on as it is.

    One line that points at the task's brief, and the scope declaration the
    spawn gate reads (`gates/spawn.py`: a ```gatekit-scope fence holding one
    JSON object). Nothing else is handed over: what to read, what to run and
    what to answer are in the brief, so the session that hands the task over
    does not write it a second time. Paths are relative to the project root.
    """
    task_id = str(task.get("id", "?"))
    scope = task.get("write_scope")
    if isinstance(scope, list):
        scope = [str(s) for s in scope]
    else:
        scope = "read-only"
    fence = json.dumps(
        {
            "write_scope": scope,
            "stop_when": "jobs complete %s prints passed" % task_id,
            "tools": "inherit",
        },
        ensure_ascii=False,
    )
    brief = "%s/jobs/%s/tasks/%s/prompt.md" % (paths.STATE_DIRNAME, job_id, task_id)
    return "\n".join([
        "Read %s and do that task. Reply with one line." % brief,
        "",
        "```gatekit-scope",
        fence,
        "```",
    ])


def handoffs(root, job: dict) -> list:
    """`(plan row, handoff text)` for every task of *job* that is handed out.

    A task is handed out when its round holds two or more tasks
    (`parallel_candidate`); the single task of a round is not in the list.
    """
    jdir = job_dir(root, str(job.get("job_id")))
    out = []
    for row in job.get("plan") or []:
        if not row.get("parallel_candidate"):
            continue
        task = read_json(_task_dir(jdir, str(row.get("id"))) / "task.json", None)
        if isinstance(task, dict):
            out.append((row, handoff_text(str(job.get("job_id")), task)))
    return out


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
    """ADR-0009 decision 1: run every task's gates once before the job starts.

    Writes `tasks/<id>/preflight.json`. Returns
    `{"passed": [ids], "warnings": [str]}`. Raises `GatePreflightError` when a
    gate is a broken command, before any task is queued.
    """
    passed, warnings, broken = [], [], []
    for task in tasks:
        task_id = str(task.get("id"))
        result = run_gates(root, task)
        write_json(_task_dir(jdir, task_id) / "preflight.json", result)
        gates = result.get("gates") or []
        if result.get("total", 0) > 0 and result.get("verdict") == verdict.OK:
            detail = "gates passed at preflight; nothing left to implement"
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
            "no code change could make it pass:\n" + "\n".join(broken)
        )
    return {"passed": passed, "warnings": warnings}


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


# ---------------------------------------------------------------- subcommands


def start(root, task_ids=None, dry_run=False, no_preflight=False) -> dict:
    """Create a job directory and hand back the ordered plan. Starts nothing.

    Every selected task gets its directory: `task.json`, the brief
    `prompt.md`, and `status.json` as `queued`. ADR-0009: unless
    `no_preflight`, every task's gates run once first (see `preflight`), and
    a task whose gates already pass is recorded `passed`. ADR-0013: the
    session that called this implements each remaining task and calls
    `complete_task`, which runs the task's gates.
    """
    cfg = config.load(root)
    build_cfg = cfg.get("build") or {}
    tasks = load_tasks(root)
    # Every task of the spec, kept apart from the selection below: a brief names
    # the paths of the tasks it depends on, and `--tasks` may leave those out.
    all_tasks = list(tasks)
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

    # ADR-0014: the budget binds here. Starting a fresh job was how it was
    # escaped on gk-trial2 — the counter lived in status.json, which `start`
    # resets — so the count is kept per task, across jobs.
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

    job_id = new_job_id()
    jdir = job_dir(root, job_id)
    (jdir / "tasks").mkdir(parents=True, exist_ok=True)

    job = {
        "version": 1,
        "job_id": job_id,
        "started_at": _now(),
        "dry_run": bool(dry_run),
        "no_preflight": bool(no_preflight),
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
            build_prompt(task, job_id, root=root, tasks=all_tasks), encoding="utf-8"
        )
        _set_status(jdir, task_id, state="queued", attempt=1, created_at=_now())

    if dry_run:
        return job

    if not no_preflight:
        pre = preflight(root, jdir, tasks)  # raises GatePreflightError before any task is queued
        job["preflight_warnings"] = pre["warnings"]
        job["preflight_passed"] = pre["passed"]
        write_json(jdir / "job.json", job)
        already = set(pre["passed"])
        tasks_to_run = [t for t in tasks if str(t.get("id")) not in already]
    else:
        tasks_to_run = list(tasks)

    # ADR-0013 decision 1: hand the ordered plan back and stop. Nothing is
    # started here. A round with one task is done by the session that called
    # this; a round with more is handed out, one subagent per task, and the
    # plan marks those tasks (`HOST_PARALLEL_HANDOFF`). Either way the task is
    # recorded by `complete_task`, which runs its gates.
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
                        detail="awaiting the host session")
    job["plan"] = plan
    write_json(jdir / "job.json", job)
    return job


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
    if state != "passed" and state not in ATTEMPT_FAILURE_STATES:
        return consecutive_failures(root, task_id)

    # The tasks of a round are built at the same time, each ending in its own
    # `jobs complete`: without the lock one run's count overwrites another's.
    with _file_lock(_attempts_path(root)):
        data = read_attempts(root)
        tasks = data.setdefault("tasks", {})
        entry: dict = tasks.get(task_id)
        if not isinstance(entry, dict):
            entry = {"failures": 0}

        if state == "passed":
            entry = {"failures": 0}
        else:
            try:
                entry["failures"] = int(entry.get("failures", 0) or 0) + 1
            except (TypeError, ValueError):
                entry["failures"] = 1
            entry["last_job"] = str(job_id)
            entry["last_gate"] = str(gate)

        entry["updated_at"] = _now()
        tasks[task_id] = entry
        data["version"] = 1
        write_json(_attempts_path(root), data)
    return int(entry.get("failures", 0) or 0)


def clear_attempts(root, task_id: str) -> None:
    """Forget one task's failures — `--force-retry`, the operator saying they
    changed something. Per task, never global."""
    with _file_lock(_attempts_path(root)):
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

    `/gatekit-tasks` shows this before writing `spec/04-tasks.md`, because
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


def complete_task(root, task_id: str, job_id: Optional[str] = None) -> dict:
    """Run an implemented task's gates and record the verdict.

    Whoever wrote the code, a subagent or the session, the gates alone decide
    whether the task passed. Writes the task's `gates.json` and `status.json`.
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
    # ADR-0014: every completed attempt counts, and the count follows the task across jobs.
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
        # Who wrote the code is not recorded: a subagent and the session run the same command.
        detail="complete: %d/%d gates %s"
        % (gates["passed"], gates["total"], gates["verdict"]),
    )


def recheck(root, task_ids=None, job_id: Optional[str] = None) -> dict:
    """Re-run a task's gates against the working tree. No new job, no attempt counted.

    ADR-0013 decision 3. A gate names test files and commands that do not exist
    until the work is done, so refining one mid-build is normal — on the
    gk-trial2 run 28 of 35 task runs existed only because a gate moved
    while the code was already correct. The right response to a moved gate is
    to run it, which takes seconds; re-deriving the code takes minutes.

    Gates are read from the **current** `spec/04-tasks.md`, not from the job's
    snapshot, since the point is to pick up the edit. Verdicts are recorded
    exactly as `complete_task` records them, `unverified` included — a gate that
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
            detail="recheck: %d/%d gates %s"
            % (gates["passed"], gates["total"], gates["verdict"]),
        )
        rechecked.append(task_id)
    return {"job_id": job_id, "rechecked": rechecked, "missing": missing}


def _merge_job_json(jdir, fields: dict, fallback: Optional[dict] = None) -> dict:
    """Re-read `job.json`, apply *fields*, write it back.

    `jobs stop` and `jobs status` both write to it (`stopped_at`,
    `finished_at`), and either may hold a copy read before the other wrote. Re-reading immediately before the
    write keeps `stopped_at` and `finished_at` from erasing each other; the
    write itself is atomic, so the surviving loser is a lost field, never a
    corrupt file.
    """
    with _file_lock(jdir / "job.json"):
        job = read_json(jdir / "job.json", None)
        if not isinstance(job, dict):
            job = dict(fallback or {})
        job.update(fields)
        write_json(jdir / "job.json", job)
    return job


@contextlib.contextmanager
def _file_lock(path, wait_s: float = 5.0, stale_s: float = 30.0):
    """Cross-process mutex around a read-modify-write of the JSON file *path*.

    Used for `job.json` and for `attempts.json`. Re-reading right before the
    write narrows the lost-update window between two commands that write the
    same file but does not close it (they are separate processes). `os.mkdir`
    is atomic on every platform, so a lock directory (`<path>.lock`) serialises
    them. A lock older than *stale_s* is a crashed holder's and is
    broken; if the lock cannot be taken within *wait_s* the write proceeds
    unlocked rather than hanging a hook or a stop.

    On Windows `os.mkdir` raises PermissionError, not FileExistsError, while
    another process is still removing the folder (measured: about one call in
    a hundred under contention). That is a held lock too, so it waits; treating
    it as "cannot lock" let two writers in at once.
    """
    lock = str(path) + ".lock"
    held = False
    deadline = time.time() + wait_s
    while True:
        try:
            os.mkdir(lock)
            held = True
            break
        except (FileExistsError, PermissionError) as exc:
            if isinstance(exc, FileExistsError):
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
    # ADR-0013: `start()` returns the plan and starts nothing, so a job only
    # becomes done when `complete_task` (or `stop`) records the last terminal
    # state, and this is the first place that moment is visible. Found on a
    # real retrial where every task passed but the job never recorded when.
    if done and not finished_at:
        finished_at = _finalise_job(jdir, job).get("finished_at")
    return {
        "job_id": job_id,
        "verdict": overall,
        "started_at": job.get("started_at"),
        "finished_at": finished_at,
        "stopped_at": job.get("stopped_at"),
        "preflight_warnings": job.get("preflight_warnings") or [],
        "done": done,
        "tasks": rows,
    }


def stop(root, job_id: Optional[str] = None) -> dict:
    """End a job early: every task that has not finished becomes `stopped`.

    A job starts no process, so there is nothing to signal. What this closes
    is the record: an open job is named on every prompt and stamped at every
    compaction, so a job the session will not finish has to be ended, and
    this is the one command that does it. `stopped` is not a verdict on the
    work; the job verdict reports it as `fail` (not done).
    """
    job_id = job_id or latest_job_id(root)
    if not job_id:
        raise ValueError("no job to stop under .gatekit/jobs/")
    jdir = job_dir(root, job_id)
    job = read_json(jdir / "job.json", None)
    if not job:
        raise ValueError("job %s has no job.json" % job_id)

    stopped = []
    for task_id in job.get("tasks", []):
        st = read_json(_task_dir(jdir, task_id) / "status.json", {}) or {}
        if st.get("state", "queued") in TERMINAL_STATES:
            continue
        _set_status(jdir, task_id, state="stopped", finished_at=_now(),
                    detail="stopped by jobs stop")
        stopped.append(task_id)

    job = _merge_job_json(jdir, {"stopped_at": _now()}, job)
    # Every task is finished now, so the job is too. Stamp it here: `finished_at` is what
    # the prompt hook reads, and without it a job that was just ended is still named as the
    # live build on every prompt until something calls `jobs status`.
    if not job.get("finished_at"):
        _finalise_job(jdir, job)
    return {"job_id": job_id, "stopped": stopped}


def results(root, job_id: Optional[str] = None) -> dict:
    return status(root, job_id)


class RetryBudgetExceeded(Exception):
    """Raised when `start` is asked to run a task whose consecutive failures
    have reached `build.max_retries`."""


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


#: Every `jobs` subcommand, in help order: (name, argument synopsis, extra help
#: lines). The one list `run` dispatches against and `_usage` prints from, so
#: a command cannot be reachable without being listed (tests/test_jobs.py
#: holds the other direction: every branch in `run` and every flag it reads).
COMMANDS = (
    ("start", "[--tasks id,id] [--dry-run] [--no-preflight]",
     ("[--force-retry id,id] [--json]",
      "--force-retry clears the listed tasks' consecutive-failure",
      "count before starting (ADR-0014)")),
    ("shape", "[--tasks id,id] [--json]",
     ("task count and rounds of the current spec/04-tasks.md;",
      "starts nothing")),
    ("status", "[--job ID] [--compact|--json]", ()),
    ("results", "[--job ID] [--compact|--json]", ()),
    ("complete", "<task_id> [--job ID]",
     ("run an implemented task's gates and record",
      "the verdict")),
    ("recheck", "[task_id ...] [--task a,b] [--job ID] [--json]",
     ("re-run gates from the current spec/04-tasks.md;",
      "no new job, no attempt counted")),
    ("stop", "[--job ID]",
     ("end a job early: unfinished tasks become stopped",)),
    ("clean", "[--all]", ()),
)
COMMAND_NAMES = tuple(name for name, _synopsis, _notes in COMMANDS)

_USAGE_NOTE_INDENT = " " * 25


def _usage() -> str:
    lines = ["usage: %s jobs <command> [--root DIR]" % paths.cli_invocation()]
    for name, synopsis, notes in COMMANDS:
        lines.append("  %s %s" % (name, synopsis))
        lines.extend(_USAGE_NOTE_INDENT + note for note in notes)
    return "\n".join(lines) + "\n"


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
            skip = arg in ("--root", "--job", "--task", "--tasks", "--force-retry")
            continue
        out.append(arg)
    return out


def _print_table(payload: dict) -> None:
    print("job %s  verdict=%s" % (payload.get("job_id"), payload.get("verdict")))
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
    if cmd not in COMMAND_NAMES:
        print("jobs: unknown command %r\n" % cmd, file=sys.stderr)
        sys.stderr.write(_usage())
        return 2
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
                dry_run="--dry-run" in rest,
                no_preflight="--no-preflight" in rest,
            )
            payload = status(root, job["job_id"])
            # The text to hand a task over with is printed here and kept nowhere:
            # `job.json` holds the plan, and the text is built from it on the spot.
            texts = {row["id"]: text for row, text in handoffs(root, job)}
            if "--json" in rest:
                payload["plan"] = [
                    dict(row, handoff=texts[row["id"]]) if row["id"] in texts else dict(row)
                    for row in job.get("plan") or []
                ]
                print(json.dumps(payload, indent=2))
            else:
                _print_table(payload)
                for line in payload.get("preflight_warnings") or []:
                    print("  warn: %s" % line)
                for row in job.get("plan") or []:
                    if row["id"] in texts:
                        print("\nhand off %s (round %d):" % (row["id"], row["round"]))
                        print(texts[row["id"]])
            return 0 if payload["verdict"] != verdict.FAIL else 1

        if cmd == "stop":
            result = stop(root, job_id)
            print("job %s stopped — %d task(s) marked stopped" % (
                result["job_id"], len(result["stopped"])))
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

    # Listed in COMMANDS but handled by no branch above: a bug in this file,
    # not in what the caller typed.
    raise AssertionError("jobs: command %r is listed but not dispatched" % cmd)
