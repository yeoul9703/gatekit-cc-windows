"""Small tools that know nothing about gatekit: read JSON, write files safely, tell the time.

Every module that reads a JSON state file, writes one, or stamps a job time goes
through these, so each of those jobs is done in exactly one place. Standard
library only, and no other gatekit module is imported here: this file sits
below all of them and has to stay that way.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
from typing import Any


def now_iso() -> str:
    """The current UTC time as ``2026-09-30T12:00:00Z`` (whole seconds).

    Job ids, job and task status files use this form, so their stamps sort as
    text. (Approvals, the contract and the ledger keep their own
    ``+00:00`` form: files already on disk and the code reading them expect it.)
    """
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: str | os.PathLike[str], default: Any = None) -> Any:
    """The JSON stored at *path*, or *default* if it cannot be read.

    "Cannot be read" covers a missing file, a permission error and text that is
    not valid JSON (or not UTF-8). None of those raise: a state file may be
    absent or half-written, and each caller already knows what to do then (an
    empty ledger, the default config, "no job yet"). What comes back is
    whatever the file holds, so a caller that needs an object checks
    ``isinstance(data, dict)`` itself.
    """
    try:
        with open(str(path), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def replace_file(src: str, dst: str, attempts: int = 40, delay_s: float = 0.05) -> None:
    """``os.replace`` that tolerates Windows sharing violations.

    POSIX replaces atomically no matter who has the destination open. On
    Windows ``os.replace`` raises ``PermissionError`` while another thread or
    process is reading or replacing the same file, which for gatekit's status,
    ledger and config files is a transient condition; retry for about two
    seconds before giving up. Elsewhere this is a plain ``os.replace``.
    """
    import time

    for attempt in range(attempts if os.name == "nt" else 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if os.name != "nt" or attempt == attempts - 1:
                raise
            time.sleep(delay_s)


def write_text_atomic(path: str | os.PathLike[str], text: str) -> None:
    """Write *text* to *path* as UTF-8, all at once or not at all.

    The text goes to a temp file next to the target (so the final rename stays
    on one filesystem) and is flushed to disk, then :func:`replace_file` puts it
    in place. A reader therefore sees the old file or the new one, never half
    of either, and a crash mid-write leaves the old file alone. Missing parent
    directories are created. If anything fails the temp file is removed and the
    error is raised.
    """
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Imported here, not at the top: tempfile pulls in shutil and random (about
    # 25 ms), which a hook that never writes should not pay for.
    import tempfile

    handle, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=".%s." % target.name, suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(tmp_name, str(target))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_json_atomic(path: str | os.PathLike[str], data: Any) -> None:
    """Write *data* to *path* as indented UTF-8 JSON with :func:`write_text_atomic`.

    *data* is serialized first, so data that cannot be turned into JSON fails
    before any file or directory is touched.
    """
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
