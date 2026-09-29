"""The hook stdin/stdout contract, and the safety wrapper every gate uses.

Claude Code invokes a gate as a subprocess, writes one JSON object to its
stdin, and reads stdout for a decision. The output shapes below were verified
against the official documentation (code.claude.com/docs/en/hooks) and match
ARCHITECTURE.md section 3:

* ``PreToolUse`` deny  → nested ``hookSpecificOutput.permissionDecision``
* ``Stop`` block       → **top-level** ``decision`` / ``reason``
* ``UserPromptSubmit`` → nested ``hookSpecificOutput.additionalContext``
  (a root-level ``additionalContext`` is silently ignored by Claude Code)

The single most important property here is that :func:`run` **always exits 0**.
A gate that crashes with a non-zero status would surface as a hook failure in
the user's session; gatekit's rule is that a broken gate degrades to "allow"
and leaves a one-line diagnostic in ``.gatekit/runs/hook-errors.log``.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys
from typing import Any, Callable, Dict, Optional, TextIO

from . import paths

#: Upper bound on injected UserPromptSubmit context (ARCHITECTURE.md section 3).
MAX_CONTEXT_CHARS = 600

Event = Dict[str, Any]
Handler = Callable[[Event], Optional[Dict[str, Any]]]


# --------------------------------------------------------------------------
# input
# --------------------------------------------------------------------------
def read_event(stream: Optional[TextIO] = None) -> Event:
    """Parse the hook event object from *stream* (default stdin).

    Any malformed or non-object payload yields ``{}`` so that a handler sees a
    well-typed dict and can decide to allow rather than crash.
    """
    source = stream if stream is not None else sys.stdin
    try:
        raw = source.read()
    except (OSError, ValueError):  # pragma: no cover - closed stdin
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def session_id(event: Event) -> str:
    """Session id from the event, or a stable placeholder when absent."""
    return str(event.get("session_id") or "unknown-session")


def event_root(event: Event) -> pathlib.Path:
    """Project root for this event, resolved from the event's ``cwd``."""
    return paths.project_root(event.get("cwd") or None)


# --------------------------------------------------------------------------
# output payloads
# --------------------------------------------------------------------------
def allow() -> None:
    """Explicit no-op: printing nothing and exiting 0 permits the action."""
    return None


def deny(reason: str) -> Dict[str, Any]:
    """PreToolUse deny payload. *reason* is shown to Claude, not the user."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": str(reason),
        }
    }


def block_stop(reason: str) -> Dict[str, Any]:
    """Stop block payload — top-level ``decision``/``reason`` per the docs."""
    return {"decision": "block", "reason": str(reason)}


def add_context(text: str) -> Optional[Dict[str, Any]]:
    """UserPromptSubmit context payload, truncated to :data:`MAX_CONTEXT_CHARS`.

    Returns ``None`` for empty text so the gate prints nothing at all rather
    than an empty context block.
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_CONTEXT_CHARS:
        cleaned = cleaned[: MAX_CONTEXT_CHARS - 1].rstrip() + "…"
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": cleaned,
        }
    }


# --------------------------------------------------------------------------
# error logging
# --------------------------------------------------------------------------
def log_error(root: pathlib.Path, event_name: str, err: BaseException) -> None:
    """Append one line ``iso_ts event_name error`` to the hook error log.

    Best effort by design: it is called from the failure path, so it must never
    raise a second exception. Newlines in the message are flattened to keep the
    log one record per line.
    """
    try:
        message = f"{type(err).__name__}: {err}".replace("\r", " ").replace("\n", " ")
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        target = paths.hook_error_log(root)
        paths.ensure_dir(target.parent)
        with open(target, "a", encoding="utf-8") as stream:
            stream.write(f"{stamp} {event_name or 'unknown'} {message}\n")
    except BaseException:  # pragma: no cover - logging must never escalate
        pass


# --------------------------------------------------------------------------
# the wrapper
# --------------------------------------------------------------------------
def run(
    handler: Handler,
    stdin: Optional[TextIO] = None,
    exit_process: bool = True,
) -> int:
    """Read the event, call *handler*, print its payload, and exit 0.

    Never raises. Any exception from the handler (including
    ``KeyboardInterrupt`` and a payload that will not serialize) is logged and
    swallowed, and the gate falls through to "allow".

    *exit_process* is only turned off by the test suite, which needs the return
    value instead of a terminated interpreter.
    """
    event: Event = {}
    code = 0
    try:
        event = read_event(stdin)
        payload = handler(event)
        if payload:
            sys.stdout.write(json.dumps(payload, ensure_ascii=False))
            sys.stdout.write("\n")
            sys.stdout.flush()
    except BaseException as err:  # noqa: BLE001 - deliberate catch-all
        try:
            log_error(event_root(event), str(event.get("hook_event_name") or ""), err)
        except BaseException:  # pragma: no cover
            pass
        code = 0

    if exit_process:  # pragma: no cover - process exit is not testable in-proc
        sys.exit(code)
    return code
