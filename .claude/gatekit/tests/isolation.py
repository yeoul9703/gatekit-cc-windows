"""Keep the gate processes a test starts out of this repository's own state folder.

A gate finds its project from the event's ``cwd``. When the event has none, or
one that cannot be used (empty stdin, ``{not json``, ``cwd: 12345``), it falls
back to the working directory of its own process (``hookio.event_root`` and
``hookio._error_log_root``). A test process runs in ``.claude/gatekit``, so a
gate started without a working directory takes this repository for its project
and writes to the real ``.gatekit/runs/``: a line in ``hook-errors.log`` that
no hook of a session produced, and an ``unknown-session.json`` that grows by
one event per test run.

So a test never calls ``subprocess.run`` for a gate itself. It calls
:func:`run_gate`, which has no default working directory:

    from tests import isolation

    proc = isolation.run_gate([sys.executable, str(GATE_SCRIPT)], cwd=self.root,
                              input=json.dumps(event), capture_output=True, text=True)

Everything but ``cwd`` goes to ``subprocess.run`` unchanged: each test keeps
its own environment, encoding and timeout.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
from typing import Any, Sequence, Union

from gatekit import paths

#: The project a gate lands in when nothing tells it where it is: the repository
#: this test suite is part of.
THIS_REPOSITORY = paths.project_root(str(pathlib.Path(__file__).resolve().parent))


def run_gate(argv: Sequence[str], *, cwd: Union[str, "os.PathLike[str]"],
             **kwargs: Any) -> "subprocess.CompletedProcess[Any]":
    """``subprocess.run(argv, cwd=cwd, **kwargs)`` for a gate or the launcher.

    *cwd* is required and must be a folder whose project is not this
    repository: the test's own temporary project. Anything else raises before
    the process starts, so a test cannot leak by leaving the argument out or by
    passing a folder inside the checkout.
    """
    folder = pathlib.Path(cwd)
    if not folder.is_dir():
        raise ValueError("run_gate: cwd is not a folder: %s" % folder)
    if paths.project_root(str(folder)) == THIS_REPOSITORY:
        raise ValueError(
            "run_gate: %s belongs to this repository, so the gate would write to its real "
            ".gatekit/. Pass the test's temporary project (one that has its own .gatekit/)."
            % folder)
    return subprocess.run(list(argv), cwd=str(folder), **kwargs)
