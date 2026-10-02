"""Project configuration: ``.gatekit/config.json`` with defaults.

A missing or corrupt config file must never stop a gate, so :func:`load` always
returns a complete, usable dictionary: the file is deep-merged onto
:data:`DEFAULTS` and anything unparseable falls back to the defaults entirely.

The file is optional: setup does not write one, and every setting has its
default here. It is read as UTF-8 with or without a BOM, because a file saved by
Windows PowerShell 5.1 (``Set-Content -Encoding UTF8``) carries one, and a
setting a person edited by hand must not be dropped without a word. A key this
module does not know (one written by an older kit) passes through the merge
and is read by nothing.
"""
from __future__ import annotations

import copy
import json
import pathlib
from typing import Any, Dict

# Re-exported so callers keep using config.write_json_atomic: one definition, in util.
from gatekit.util import write_json_atomic, write_text_atomic  # noqa: F401

from . import paths

DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "enforce_spec_before_code": True,
    # How many consecutive failures of one task `jobs start` accepts before it
    # refuses the task (ADR-0014). 0 turns the limit off.
    "build": {"max_retries": 2},
    "questions": {"interview_max_calls": 2, "items_per_call": 4},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *override* onto a copy of *base*.

    Dictionaries merge key by key; every other value (lists included) is
    replaced wholesale. Replacing lists is deliberate: a user who writes a
    list means exactly that list, not the default with extras.
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
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)
    if not isinstance(raw, dict):
        return copy.deepcopy(DEFAULTS)
    return _deep_merge(DEFAULTS, raw)


def save(root: pathlib.Path, cfg: Dict[str, Any]) -> None:
    """Write *cfg* to ``.gatekit/config.json`` atomically."""
    target = paths.config_file(root)
    write_json_atomic(target, cfg)
