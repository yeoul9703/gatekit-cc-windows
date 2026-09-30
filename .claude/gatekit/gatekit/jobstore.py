"""Where jobs live and which states end a task: the light half of ``jobs.py``.

Hooks need to know which job is newest, where its files are and whether a task
is finished, without importing ``jobs.py`` (the runner: workers, spec checks,
subprocess handling; over a hundred milliseconds of import on a hook that has
maybe a hundred to spend). Everything here reads only ``paths``, so a hook can
import it freely. ``jobs.py`` and ``spec.py`` take their names from here.
"""
from __future__ import annotations

import pathlib
from typing import Optional

from . import paths

#: States after which a task will not change again on its own. The one place
#: this list is written down: ``jobs.py`` (job verdict, ``stop``) and
#: ``spec.py`` (is PROGRESS.md older than the latest result?) both import it, so
#: a task that was stopped or blocked counts as finished in both.
#: A task moves through queued -> running -> gating and ends in one of these
#: (``stopped``: ended by ``jobs stop``; ``blocked``: a dependency did not pass).
TERMINAL_STATES = ("passed", "failed", "timeout", "redelegated", "stopped", "blocked")


def job_dir(root: pathlib.Path, job_id: str) -> pathlib.Path:
    """``<root>/.gatekit/jobs/<job_id>``: the directory holding one job."""
    return paths.jobs_dir(root) / job_id


def latest_job_id(root: pathlib.Path) -> Optional[str]:
    """The newest job's id, or ``None`` when no job has been started.

    Job ids start with a UTC timestamp, so the last name in sorted order is the
    newest. A directory without a ``job.json`` (a job being created, or
    something else that landed there) is not a job.
    """
    base = paths.jobs_dir(root)
    if not base.is_dir():
        return None
    names = sorted(p.name for p in base.iterdir() if (p / "job.json").is_file())
    return names[-1] if names else None
