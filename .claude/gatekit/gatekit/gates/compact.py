"""PreCompact gate — stamp the live build state into spec/PROGRESS.md.

ADR-0013 decision 1a. With `build.execution = "host"` a build lives in the
session that runs it, so the host's compaction is a normal event rather than
an exceptional one. Nothing here is a recovery mechanism: everything a build
must not forget is *already* on disk — `status.json` per task, `gates.json`,
the job dir — because gatekit's stages talk through files, never through
conversation memory. What a compaction removes is the narrative.

So this hook writes the narrative down: one section in `spec/PROGRESS.md`
naming the job, its execution mode, and every task's state, so the session
that comes back after the summary can pick up from a file instead of from
what survived the summariser.

The section is delimited and rewritten in place, so repeated compactions leave
one stamp rather than a pile. Everything a human or another pipeline wrote is
untouched — the hook only ever replaces its own block.

Like every gate here it exits 0 on any internal error and never blocks.
"""
from __future__ import annotations

import datetime
import pathlib
from typing import Any, Dict, Optional

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import hookio, jobs, paths  # noqa: E402

#: Opening line of the block this hook owns. Anything between it and
#: END_MARKER is replaced wholesale on the next compaction; nothing outside is
#: ever touched.
SECTION_MARKER = "<!-- gatekit:build-state -->"
END_MARKER = "<!-- /gatekit:build-state -->"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_state(root) -> Optional[Dict[str, Any]]:
    """The latest job's task states, or ``None`` when there is no job."""
    job_id = jobs.latest_job_id(root)
    if not job_id:
        return None
    jdir = jobs.job_dir(root, job_id)
    job = jobs.read_json(jdir / "job.json", None)
    if not isinstance(job, dict):
        return None

    rows = []
    for task_id in job.get("tasks") or []:
        status = jobs.read_json(jdir / "tasks" / str(task_id) / "status.json", {})
        if not isinstance(status, dict):
            status = {}
        rows.append({
            "id": str(task_id),
            "state": str(status.get("state", "queued")),
            "gates": "%s/%s" % (status.get("gates_passed", 0), status.get("gates_total", 0)),
            "detail": str(status.get("detail", ""))[:120],
        })
    return {
        "job_id": job_id,
        "execution": str(job.get("execution", "worker")),
        "backend": str((job.get("backend") or {}).get("name", "")),
        "finished": bool(job.get("finished_at")),
        "tasks": rows,
    }


def render(state: Dict[str, Any]) -> str:
    """The replaceable block, as Markdown."""
    passed = sum(1 for r in state["tasks"] if r["state"] == "passed")
    total = len(state["tasks"])
    lines = [
        SECTION_MARKER,
        "",
        "## Build state at last compaction",
        "",
        "Written by gatekit's PreCompact hook (ADR-0013). The conversation was "
        "summarised; this is what the run actually looked like at that moment. "
        "Read it, then continue from the first task that is not `passed`.",
        "",
        "| | |",
        "|---|---|",
        "| job | `%s` |" % state["job_id"],
        "| execution | %s |" % state["execution"],
        "| backend | %s |" % (state["backend"] or "—"),
        "| progress | %d / %d passed |" % (passed, total),
        "| job finished | %s |" % ("yes" if state["finished"] else "no"),
        "| stamped | %s |" % _now(),
        "",
        "| task | state | gates | detail |",
        "|---|---|---|---|",
    ]
    for row in state["tasks"]:
        lines.append("| `%s` | %s | %s | %s |" % (
            row["id"], row["state"], row["gates"], row["detail"].replace("|", "\\|")))
    lines += ["", END_MARKER, ""]
    return "\n".join(lines)


def splice(text: str, block: str) -> str:
    """*text* with our block replaced, or appended when it is not there yet."""
    start = text.find(SECTION_MARKER)
    if start == -1:
        separator = "" if not text or text.endswith("\n\n") else (
            "\n" if text.endswith("\n") else "\n\n")
        return text + separator + block
    end = text.find(END_MARKER, start)
    if end == -1:
        # An opening marker with no close: replace from it to the end rather
        # than leaving a half-block that would accumulate.
        return text[:start] + block
    return text[:start] + block + text[end + len(END_MARKER):].lstrip("\n")


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Stamp the build state. Never blocks, never raises."""
    root = hookio.event_root(event)
    state = build_state(root)
    if state is None or not state["tasks"]:
        return hookio.allow()

    path = paths.spec_dir(root) / "PROGRESS.md"
    try:
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError:
        existing = ""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(splice(existing, render(state)), encoding="utf-8")
    except OSError:
        # A build state we could not record must not break the compaction;
        # the job dir still holds every fact this block would have carried.
        pass
    return hookio.allow()


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()
