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
    "workers":  ("gatekit.workers",  "Worker backends: list / check / set-default (claude default, codex optional)."),
    "ledger":   ("gatekit.ledger",   "Session ledger: show / init / set-pipeline."),
    "lang":     ("gatekit.lang",     "Detect output language for a text (ko/en)."),
    "install":  ("gatekit.hosts",    "Generate a host layer (--host codex): hooks, skills, AGENTS.md block."),
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("usage: python3 -m gatekit <subcommand> [args]\n")
        for name, (_, help_text) in SUBCOMMANDS.items():
            print(f"  {name:<10} {help_text}")
        return 0 if argv else 1
    name, rest = argv[0], argv[1:]
    if name not in SUBCOMMANDS:
        print(f"gatekit: unknown subcommand '{name}'", file=sys.stderr)
        return 2
    module = importlib.import_module(SUBCOMMANDS[name][0])
    return int(module.run(rest))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
