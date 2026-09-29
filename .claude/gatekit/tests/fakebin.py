"""Fake command-line executables that run on Windows and POSIX alike.

A `#!/bin/sh` script cannot be started by Windows (no shebang handling, and no
`/bin/cat`, `/bin/sleep`). Instead the fake is a Python script, plus, on
Windows only, a `<name>.cmd` shim so the bare name resolves through PATHEXT the
way a real `claude.cmd` or `npm.cmd` does. On POSIX the script itself is the
executable, with the current interpreter in its shebang line.
"""
from __future__ import annotations

import os
import pathlib
import stat
import sys


def make_fake(directory, name: str, source: str) -> pathlib.Path:
    """Create the executable `name` in *directory* whose behaviour is the
    Python *source*. Returns the path that PATH lookup will find."""
    directory = pathlib.Path(directory)
    if os.name == "nt":
        script = directory / (name + ".fake.py")
        script.write_text(source, encoding="utf-8")
        shim = directory / (name + ".cmd")
        shim.write_text('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, script),
                        encoding="ascii")
        return shim
    script = directory / name
    script.write_text("#!%s\n%s" % (sys.executable, source), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def print_and_exit(body: str, exit_code: int = 0, sleep: float = 0.0,
                   read_stdin: bool = False, echo_args: bool = False) -> str:
    """Python source: optionally drain stdin, sleep, print *body* (UTF-8) and
    exit with *exit_code*. With *echo_args* the arguments are printed instead."""
    newline = chr(10)
    lines = ["import sys, time"]
    if read_stdin:
        lines.append("sys.stdin.buffer.read()")
    lines.append("time.sleep(%r)" % float(sleep))
    if echo_args:
        lines.append("text = ' '.join(sys.argv[1:])")
    else:
        lines.append("text = %r" % body)
    lines.append("sys.stdout.buffer.write((text + chr(10)).encode('utf-8'))")
    lines.append("sys.stdout.flush()")
    lines.append("sys.exit(%d)" % exit_code)
    return newline.join(lines) + newline
