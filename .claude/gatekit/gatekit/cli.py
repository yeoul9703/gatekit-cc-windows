"""`python3 -m gatekit <subcommand> ...` dispatcher.

Each subcommand lives in its own module exposing `run(argv: list[str]) -> int`.
The mapping is the single registry; modules are imported lazily so a broken
subcommand never takes the others down.
"""
from __future__ import annotations

import importlib
import sys

SUBCOMMANDS = {
    "doctor":   ("gatekit.doctor",   "Diagnose install, hooks, state, workers (ok/warn/fail/unverified)."),
    "spec":     ("gatekit.spec",     "Validate the spec set (spec/01..05, RECOVERY, PROGRESS)."),
    "contract": ("gatekit.contract", "Derive and run the completion contract from spec/05-gate.md."),
    "approve":  ("gatekit.approval", "Hash-anchored approvals: approve / check / list."),
    "design":   ("gatekit.design",   "Design tokens: merge-preset / impact."),
    "jobs":     ("gatekit.jobs",     "Worker jobs: start / status / wait / results / redelegate / clean."),
    "workers":  ("gatekit.workers",  "Worker backends: list / check / set-default."),
    "ledger":   ("gatekit.ledger",   "Session ledger: show / init / set-pipeline."),
    "lang":     ("gatekit.lang",     "Detect output language for a text (ko/en)."),
}

#: Gate modules that `_gate <name>` may dispatch to. This is how
#: `.claude/settings.json` hooks reach a gate through `bin/gatekit.py _gate
#: <name>` (exec form, run by the project venv's python): the gate module reads
#: the hook event JSON from this same process's stdin.
GATES = ("prompt", "write", "bash", "spawn", "question", "compact", "stop", "tokens")


def _force_utf8_stdio() -> None:
    """Make stdin/stdout/stderr UTF-8 regardless of the console code page.

    Hooks receive JSON on stdin and answer JSON on stdout, and Claude Code
    speaks UTF-8 both ways. Python on Windows otherwise uses the ANSI code
    page (cp1252/cp949) for pipes, which turns Korean prompts into mojibake and
    writes non-UTF-8 bytes (e.g. an em dash as 0x97) that the reader decodes as
    U+FFFD. On macOS/Linux the streams are already UTF-8, so this is a no-op
    there. Streams without ``reconfigure`` (test doubles) are left alone.
    """
    for name, errors in (("stdin", "replace"), ("stdout", "replace"), ("stderr", "replace")):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if name == "stdin":
                reconfigure(encoding="utf-8", errors=errors)
            else:
                reconfigure(encoding="utf-8", errors=errors, newline="\n")
        except (ValueError, OSError):  # pragma: no cover - detached/closed stream
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("usage: python3 -m gatekit <subcommand> [args]\n")
        for name, (_, help_text) in SUBCOMMANDS.items():
            print(f"  {name:<10} {help_text}")
        print(f"  _gate      Run a gate directly (used by hooks): {', '.join(GATES)}")
        return 0 if argv else 1
    name, rest = argv[0], argv[1:]
    if name == "_gate":
        if not rest or rest[0] not in GATES:
            print(f"gatekit: unknown gate '{rest[0] if rest else ''}'", file=sys.stderr)
            return 2
        gate_module = importlib.import_module(f"gatekit.gates.{rest[0]}")
        try:
            # Hook gates (prompt/write/bash/spawn/question/compact/stop) take
            # no argv and read the event from stdin. The task gate ("tokens")
            # takes an argv list instead, so try that shape first.
            return int(gate_module.main(rest[1:]) or 0)
        except TypeError:
            gate_module.main()
            return 0
    if name not in SUBCOMMANDS:
        print(f"gatekit: unknown subcommand '{name}'", file=sys.stderr)
        return 2
    module = importlib.import_module(SUBCOMMANDS[name][0])
    return int(module.run(rest))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
