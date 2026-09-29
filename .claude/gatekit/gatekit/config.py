"""Project configuration: ``.gatekit/config.json`` with defaults.

A missing or corrupt config file must never stop a gate, so :func:`load` always
returns a complete, usable dictionary: the file is deep-merged onto
:data:`DEFAULTS` and anything unparseable falls back to the defaults entirely.

Sandboxing is never disabled by default. A backend that passes a bypass flag has
to say so explicitly with ``"unsafe": true``, and the job receipt records it.
Each backend carries two argv lists: ``argv`` for build workers and
``read_only_argv`` for the evaluator, which must never be able to write.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import tempfile
from typing import Any, Dict

from . import paths

DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "enforce_spec_before_code": True,
    "worker": {
        "default": "claude",
        "backends": {
            "claude": {
                "argv": [
                    "claude",
                    "-p",
                    "--output-format",
                    "json",
                    "--permission-mode",
                    "acceptEdits",
                ],
                "read_only_argv": [
                    "claude",
                    "-p",
                    "--output-format",
                    "json",
                    "--permission-mode",
                    "plan",
                ],
                "enabled": True,
            },
            "codex": {
                "argv": ["codex", "exec", "--sandbox", "workspace-write"],
                "read_only_argv": ["codex", "exec", "--sandbox", "read-only"],
                "enabled": False,
            },
        },
    },
    # ADR-0013: `execution` names who implements a task — "host" (the
    # session running the build) or "worker" (a spawned backend). "host" is
    # the default: a worker is a cold session of the same model, paying a
    # fresh project discovery per task to buy a second opinion from the
    # model already present. On the `gk-trial2` run that measured this, 26
    # minutes of real work took 4.5 hours across 35 spawns. Spawn a worker
    # when the model must actually differ (adversarial verification, a
    # Codex host delegating to Claude) or when a round holds enough
    # independent tasks for parallelism to pay — both decided per round,
    # not by this default. A project that wants the old behaviour sets
    # `"execution": "worker"` explicitly.
    "build": {"max_retries": 2, "parallel": 3, "task_timeout_s": 900,
              "execution": "host"},
    "questions": {"interview_max_calls": 2, "items_per_call": 4},
    # Who grades in /gatekit:verify: "agent" spawns a read-only subagent of
    # the host; a backend name runs that CLI with its read_only_argv, so the
    # grader can be a different model from the one that built the code.
    # Unset by design (ADR-0013): an absent evaluator resolves at call time
    # to an enabled backend whose name differs from the host, so the grader
    # is not the model that wrote the code. A user who wants the host's own
    # subagent writes "agent" here explicitly and that always wins.
    "verify": {"evaluator": ""},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *override* onto a copy of *base*.

    Dictionaries merge key by key; every other value (lists included) is
    replaced wholesale. Replacing lists is deliberate: a user who writes an
    ``argv`` means that exact command line, not the default with extras.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load(root: pathlib.Path) -> Dict[str, Any]:
    """Return the effective config for the project at *root*.

    Always a fresh deep copy, so callers may mutate the result without
    poisoning :data:`DEFAULTS` for the rest of the process.
    """
    target = paths.config_file(root)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)
    if not isinstance(raw, dict):
        return copy.deepcopy(DEFAULTS)
    return _deep_merge(DEFAULTS, raw)


def save(root: pathlib.Path, cfg: Dict[str, Any]) -> None:
    """Write *cfg* to ``.gatekit/config.json`` atomically."""
    target = paths.config_file(root)
    write_json_atomic(target, cfg)


def write_json_atomic(target: pathlib.Path, payload: Any) -> None:
    """Serialize *payload* to *target* via a temp file plus ``os.replace``.

    Shared by every module that persists JSON state. A crash mid-write leaves
    the previous file intact rather than a truncated one; the temp file is
    created in the destination directory so the replace stays on one filesystem.
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
    write_text_atomic(target, text + "\n")


def write_text_atomic(target: pathlib.Path, text: str) -> None:
    """Write *text* to *target* via a temp file plus ``os.replace``."""
    target = pathlib.Path(target)
    paths.ensure_dir(target.parent)
    handle, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, str(target))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
