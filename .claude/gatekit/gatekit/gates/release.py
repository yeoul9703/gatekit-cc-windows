"""Release hook — a subagent's write scope is dropped when that agent ends.

The spawn gate (:mod:`gatekit.gates.spawn`) records the ``write_scope`` of
every subagent so that a second agent over the same files is refused. Without
this hook the record outlives the agent, and the next round over those files
is refused for the rest of the session.

It is registered twice and reads two events (measured, ADR-0022):

* ``PostToolUse`` with matcher ``Agent|Task`` carries the ``tool_use_id`` of
  the spawning call — the id the spawn gate stored with the scope — and
  ``tool_response.agentId``, the id of the agent that call started.

  - ``tool_response.status == "completed"``: a foreground agent. The call
    returns when the agent has ended, so the scope with that ``tool_use_id``
    is released.
  - ``"async_launched"``: a background agent. This event fires a few
    milliseconds after the launch, while the agent is running, so nothing is
    released. The ``agentId`` is written on the scope and the release waits
    for ``SubagentStop``.

* ``SubagentStop`` carries ``agent_id`` and fires when the agent ends. The
  scope bound to that id is released.

Every link is equality on an identifier Claude Code issued
(``tool_use_id`` → ``agentId`` → ``agent_id``). There is no matching by
description, prompt or timing: an event whose identifier matches no recorded
scope releases nothing.

For a foreground agent ``SubagentStop`` arrives *before* the ``PostToolUse``
that names its ``agentId``. An id that matches no scope while a scope is still
waiting for its id is therefore remembered (``ended_agents``), and a later
``PostToolUse`` that binds an id already in that list releases at once.

This hook **never blocks**: it has no deny path and returns no payload, and an
internal error exits 0 through :func:`hookio.run`. A project with no
``.gatekit/`` and a session with no ledger are left untouched.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import hookio, ledger, paths  # noqa: E402

SPAWN_TOOLS = ("Agent", "Task")

#: ``tool_response.status`` of a foreground agent whose call has returned.
COMPLETED = "completed"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _tool_returned(led: ledger.Ledger, event: Dict[str, Any]) -> bool:
    """PostToolUse of an Agent/Task call. Returns True when the ledger changed."""
    tool_use_id = _text(event.get("tool_use_id"))
    if led.scope_of("tool_use_id", tool_use_id) is None:
        return False
    response = event.get("tool_response")
    if not isinstance(response, dict):
        return False
    agent_id = _text(response.get("agentId"))
    finished = response.get("status") == COMPLETED and not response.get("isAsync")
    if finished or led.agent_ended(agent_id):
        return led.release_scope("tool_use_id", tool_use_id) > 0
    # Still running (a background launch): remember which agent holds the scope.
    return led.bind_agent(tool_use_id, agent_id)


def _agent_stopped(led: ledger.Ledger, event: Dict[str, Any]) -> bool:
    """SubagentStop. Returns True when the ledger changed."""
    agent_id = _text(event.get("agent_id"))
    if not agent_id:
        return False
    if led.release_scope("agent_id", agent_id):
        return True
    # No scope knows this id. If one is still waiting for its agent id, this
    # may be that agent (foreground order): keep the id for the PostToolUse.
    waiting = any(
        isinstance(entry, dict) and entry.get("tool_use_id") and not entry.get("agent_id")
        for entry in led.data.get("scopes", [])
    )
    if waiting and not led.agent_ended(agent_id):
        led.note_agent_ended(agent_id)
        return True
    return False


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Release the scope of the agent this event reports as ended. Never denies."""
    name = event.get("hook_event_name")
    if name == "PostToolUse":
        if event.get("tool_name") not in SPAWN_TOOLS:
            return hookio.allow()
        change = _tool_returned
    elif name == "SubagentStop":
        change = _agent_stopped
    else:
        return hookio.allow()

    root = hookio.event_root(event)
    session = hookio.session_id(event)
    if not paths.state_dir(root).is_dir() or not ledger.Ledger.exists(root, session):
        return hookio.allow()

    with ledger.ScopeLock(root, session) as held:
        if not held:
            return hookio.allow()  # the scope stays; `ledger release-scopes` remains
        led = ledger.Ledger.load(root, session)
        if change(led, event):
            led.save()
    return hookio.allow()


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()
