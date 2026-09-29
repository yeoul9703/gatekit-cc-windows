"""Filesystem layout resolution for gatekit.

Every other module asks this one where things live so that the layout in
ARCHITECTURE.md section 2 is stated exactly once. Two roots matter:

* the **project root** — the user's repository, found by walking up from a
  starting directory to the nearest ancestor holding ``.gatekit/`` or ``.git/``;
* the **gatekit root** — this standalone install's own directory
  (``<project>/.claude/gatekit``), derived from ``__file__`` since there is no
  plugin manager to ask.

No absolute personal path is ever hardcoded: both roots are derived at runtime.
"""
from __future__ import annotations

import os
import pathlib
from typing import Optional

#: Directory names that mark a project root, in priority order. ``.gatekit``
#: comes first so a gatekit-managed subproject inside a larger git repository
#: wins over the outer repository.
ROOT_MARKERS = (".gatekit", ".git")

STATE_DIRNAME = ".gatekit"
SPEC_DIRNAME = "spec"


def project_root(cwd: Optional[str] = None) -> pathlib.Path:
    """Return the nearest ancestor of *cwd* containing a root marker.

    Falls back to *cwd* itself when no marker is found, which keeps gates
    working in a scratch directory instead of escaping to the filesystem root.
    """
    start = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()
    try:
        start = start.resolve()
    except OSError:  # pragma: no cover - unreadable path
        start = start.absolute()

    for candidate in (start, *start.parents):
        for marker in ROOT_MARKERS:
            if (candidate / marker).is_dir():
                return candidate
    return start


def state_dir(root: pathlib.Path) -> pathlib.Path:
    """``<root>/.gatekit`` — machine state, mostly git-ignored."""
    return pathlib.Path(root) / STATE_DIRNAME


def spec_dir(root: pathlib.Path) -> pathlib.Path:
    """``<root>/spec`` — human-reviewed, committed specification set."""
    return pathlib.Path(root) / SPEC_DIRNAME


def runs_dir(root: pathlib.Path) -> pathlib.Path:
    """``<root>/.gatekit/runs`` — per-session ledgers and the hook error log."""
    return state_dir(root) / "runs"


def jobs_dir(root: pathlib.Path) -> pathlib.Path:
    """``<root>/.gatekit/jobs`` — worker job directories."""
    return state_dir(root) / "jobs"


def hook_error_log(root: pathlib.Path) -> pathlib.Path:
    """One-line-per-failure diagnostic log written by :mod:`gatekit.hookio`."""
    return runs_dir(root) / "hook-errors.log"


def config_file(root: pathlib.Path) -> pathlib.Path:
    return state_dir(root) / "config.json"


def approvals_file(root: pathlib.Path) -> pathlib.Path:
    return state_dir(root) / "approvals.json"


def contract_file(root: pathlib.Path) -> pathlib.Path:
    return state_dir(root) / "contract.json"


def gatekit_root() -> pathlib.Path:
    """Return this standalone install's own directory.

    Always derived from ``__file__``: ``gatekit/gatekit/paths.py`` ->
    ``gatekit/gatekit`` -> ``gatekit`` (i.e. ``<project>/.claude/gatekit``).
    There is no plugin manager in standalone mode, so no
    ``CLAUDE_PLUGIN_ROOT`` env var or ``.claude-plugin/plugin.json`` marker is
    consulted.
    """
    here = pathlib.Path(__file__).resolve()
    return here.parents[1]


def ensure_dir(path: pathlib.Path) -> pathlib.Path:
    """Create *path* (and parents) if absent. Returns *path* for chaining."""
    pathlib.Path(path).mkdir(parents=True, exist_ok=True)
    return pathlib.Path(path)


def relative_to_root(root: pathlib.Path, target: pathlib.Path) -> Optional[str]:
    """Return *target* as a POSIX path relative to *root*, or ``None``.

    ``None`` means the target lies outside the project root. Both sides are
    realpath-resolved first so symlinks cannot smuggle a path back in.
    """
    try:
        real_root = pathlib.Path(os.path.realpath(str(root)))
        real_target = pathlib.Path(os.path.realpath(str(target)))
        return real_target.relative_to(real_root).as_posix()
    except (ValueError, OSError):
        return None


def cli_invocation() -> str:
    """The one CLI form that works from a user's project directory.

    Used for every user-facing fix string so a copy-pasted remedy runs
    without PYTHONPATH and without the caller needing to know which Python
    interpreter is available: ``"<gatekit_root>/bin/gatekit"``. That wrapper
    finds a working Python itself and forwards to ``bin/gatekit.py``.
    """
    return '"%s"' % (gatekit_root() / "bin" / "gatekit")
