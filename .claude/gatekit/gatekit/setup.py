"""`gatekit.py setup ...`: a thin front for scripts/setup.ps1.

    gatekit.py setup [--install X,Y] [--update X] [--reinstall X] [--retry-failed]
                     [--status] [--json] [--lang ko|en]

Every option is handed to `powershell.exe -NoProfile -ExecutionPolicy Bypass -File
<setup.ps1>` unchanged. The script's output goes straight to this console and its exit
code is this command's exit code (0 ready, 1 failed, 2 needs the user, 3 restart needed,
4 blocked by policy or network). Names are NOT checked here: the script owns the allowed
lists and refuses the rest.

When uv or the .venv is broken this command cannot start at all; run the script directly:
    powershell -NoProfile -ExecutionPolicy Bypass -File .claude/gatekit/scripts/setup.ps1
"""
from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
from typing import List, Optional

from gatekit import paths

USAGE = ("usage: gatekit.py setup [--install X,Y] [--update X] [--reinstall X] [--retry-failed] "
         "[--status] [--json] [--lang ko|en]")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # argparse would exit 2, which means "needs the user" here
        raise ValueError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="gatekit.py setup", add_help=False)
    for flag in ("--install", "--update", "--reinstall"):
        parser.add_argument(flag, action="append", default=[], metavar="NAMES")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--lang", choices=("ko", "en"))
    parser.add_argument("-h", "--help", action="store_true")
    return parser


def powershell_path() -> Optional[str]:
    """Windows PowerShell 5.1 (present on every Windows), else whatever is on PATH."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = pathlib.Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if candidate.is_file():
        return str(candidate)
    return shutil.which("powershell") or shutil.which("pwsh")


def build_command(ps_exe: str, script: pathlib.Path, ns: argparse.Namespace) -> List[str]:
    command = [ps_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    for flag, values in (("-Install", ns.install), ("-Update", ns.update), ("-Reinstall", ns.reinstall)):
        if values:
            command += [flag, ",".join(values)]
    if ns.retry_failed:
        command.append("-RetryFailed")
    if ns.status:
        command.append("-Status")
    if ns.json:
        command.append("-Json")
    if ns.lang:
        command += ["-Lang", ns.lang]
    return command


def run(argv: List[str]) -> int:
    try:
        ns = _parser().parse_args(argv)
    except ValueError as exc:
        print("gatekit setup: %s\n%s" % (exc, USAGE), file=sys.stderr)
        return 1
    if ns.help:
        print(USAGE)
        print(__doc__)
        return 0
    script = paths.gatekit_root() / "scripts" / "setup.ps1"
    if not script.is_file():
        print("gatekit setup: %s not found" % script, file=sys.stderr)
        return 1
    ps_exe = powershell_path()
    if not ps_exe:
        print("gatekit setup: powershell.exe not found", file=sys.stderr)
        return 1
    sys.stdout.flush()
    sys.stderr.flush()
    # stdout/stderr are inherited (not captured): the script's own output is the output.
    return subprocess.run(build_command(ps_exe, script, ns)).returncode
