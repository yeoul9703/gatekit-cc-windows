"""Filesystem layout resolution for gatekit.

Every other module asks this one where things live so that the layout of a
project's ``spec/`` and ``.gatekit/`` folders is stated exactly once. Two roots
matter:

* the **project root** — the user's repository, found by walking up from a
  starting directory to the nearest ancestor holding ``.gatekit/`` or ``.git/``;
* the **gatekit root** — this standalone install's own directory
  (``<project>/.claude/gatekit``), derived from ``__file__`` since there is no
  plugin manager to ask. The skills (``<project>/.claude/skills/gatekit-<name>``)
  sit beside it and hold the data files the engine reads.

No absolute personal path is ever hardcoded: both roots are derived at runtime.
"""
from __future__ import annotations

import os
import pathlib
from typing import Optional

from gatekit.util import replace_file  # noqa: F401  (re-exported: one definition, in util)

#: Directory names that mark a project root, in priority order. ``.gatekit``
#: comes first so a gatekit-managed subproject inside a larger git repository
#: wins over the outer repository.
ROOT_MARKERS = (".gatekit", ".git")

STATE_DIRNAME = ".gatekit"
SPEC_DIRNAME = "spec"


def resolve_argv(argv):
    """Return *argv* as a list of strings with a Windows-runnable ``argv[0]``.

    ``subprocess`` without a shell does not apply ``PATHEXT`` on Windows, so
    ``["npm", ...]`` or ``["claude", ...]`` cannot start a ``.cmd``/``.bat``
    shim and raises FileNotFoundError even though the command works in a
    terminal. On Windows a bare command name is therefore resolved with
    ``shutil.which`` (which does honour ``PATHEXT``); if nothing is found the
    name is left as is so the caller still reports the original error. On
    macOS/Linux, and for any ``argv[0]`` that already contains a path
    separator, the list is returned unchanged.
    """
    out = [str(a) for a in argv]
    if os.name == "nt" and out and not any(sep in out[0] for sep in ("/", "\\")):
        import shutil

        found = shutil.which(out[0])
        if found:
            out[0] = found
    return out


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


def skills_root() -> pathlib.Path:
    """``<project>/.claude/skills`` — the sibling of :func:`gatekit_root`."""
    return gatekit_root().parent / "skills"


def skill_dir(name: str) -> pathlib.Path:
    """``<project>/.claude/skills/gatekit-<name>``.

    ``name`` is the bare skill name (``build``, ``verify``) or ``shared``, the
    folder of files several skills and the engine use (heading map, presets).
    """
    return skills_root() / ("gatekit-" + name)


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
    """The one CLI form users paste into a terminal, run from the project root.

    Used for every user-facing fix string. It runs unchanged in PowerShell and
    Git Bash (no quoting, no ``$VAR``, forward slashes only) and needs only uv:
    ``uv`` resolves the project venv (creating it from ``uv.lock`` if absent)
    and runs ``bin/gatekit.py`` with that interpreter.
    """
    return CLI_INVOCATION


#: See :func:`cli_invocation`. Relative to the project root on purpose: no
#: absolute personal path may appear in messages or in the repo.
CLI_INVOCATION = ("uv run --project .claude/gatekit --frozen python "
                  ".claude/gatekit/bin/gatekit.py")
