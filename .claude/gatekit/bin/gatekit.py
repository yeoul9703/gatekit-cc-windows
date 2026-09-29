#!/usr/bin/env python3
"""Launcher for the gatekit CLI from any working directory.

Run with the project venv's interpreter, as hooks do (exec form, no shell)
and as users do through ``uv run --project .claude/gatekit --frozen python
.claude/gatekit/bin/gatekit.py <subcommand> ...`` from the project root. The ``gatekit`` package lives next to
this file's parent, which is never on ``sys.path`` in a user's project, so the
launcher adds the gatekit root itself before dispatching. Nothing else about
the CLI differs from ``python3 -m gatekit``.
"""
from __future__ import annotations

import os
import sys


def _plugin_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    root = _plugin_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    from gatekit.cli import main as cli_main
    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
