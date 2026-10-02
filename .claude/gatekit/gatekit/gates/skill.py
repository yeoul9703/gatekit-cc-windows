"""PreToolUse hook for Skill — record the pipeline a model-started skill enters.

The prompt gate (:mod:`gatekit.gates.prompt`) sets ``active_pipeline`` when
the user types ``/gatekit-<name>``. When the user asks in plain words and the
model starts the skill itself, the prompt holds no skill name: the only trace
is a ``Skill`` tool call whose ``tool_input.skill`` is ``gatekit-<name>``
(measured, ADR-0021). Without this hook that path leaves ``active_pipeline``
unset, so the stop gate (build/verify) and the question budget (interview)
never engage.

This hook **never blocks**. It records and returns nothing:

* ``gatekit-<pipeline>`` sets ``active_pipeline``; ``gatekit-doctor`` and
  ``gatekit-setup`` clear it — the rule the prompt gate applies, through the
  same two functions (``prompt.skill_command`` and ``prompt.apply_name``).
* Any other skill, an unknown ``gatekit-`` name and malformed input are
  ignored without touching the ledger.
* A project with no ``.gatekit/`` is left alone and gets no state.
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
from gatekit.gates import prompt  # noqa: E402


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Record the pipeline of a ``gatekit-<name>`` skill call. Always allows."""
    if event.get("tool_name") != "Skill":
        return hookio.allow()
    tool_input = event.get("tool_input")
    skill = tool_input.get("skill") if isinstance(tool_input, dict) else None
    name = prompt.skill_command(skill) if isinstance(skill, str) else None
    if name is None:
        return hookio.allow()

    root = hookio.event_root(event)
    if not paths.state_dir(root).is_dir():
        return hookio.allow()

    led = ledger.Ledger.load(root, hookio.session_id(event))
    if prompt.apply_name(led, name):
        led.append_event("skill", {"skill": name})
        led.save()
    return hookio.allow()


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()
