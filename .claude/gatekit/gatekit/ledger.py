"""Per-session run ledger: ``.gatekit/runs/<session_id>.json``.

The ledger is the only memory shared between the gates. The prompt gate writes
the detected language, the spawn gate records write scopes and the release hook
drops them when their agent ends, the question gate counts AskUserQuestion
calls and the stop gate records the final verdict.

**Resolution is strictly by session id.** There is deliberately no "most recent
file" fallback: with two Claude Code sessions open in one project, a recency
fallback would let one session read the other's scopes and block writes that
were never in conflict. A missing id yields a fresh ledger instead.

Writes are atomic (temp file plus ``os.replace``) because a gate can be killed
at any moment by the hook timeout, and a half-written ledger would break every
subsequent gate in the session.
"""
from __future__ import annotations

import datetime
import fnmatch
import json
import os
import pathlib
import posixpath
import re
import sys
import time
from typing import Any, Dict, List, Optional, Union

from . import config, paths

#: `events` is append-only and capped; the oldest entries are dropped first.
MAX_EVENTS = 500

#: Agent ids whose SubagentStop arrived before their scope knew the id; capped.
MAX_ENDED_AGENTS = 200

#: The two identifiers a scope entry can be released by (ADR-0022).
SCOPE_KEYS = ("tool_use_id", "agent_id")

VERSION = 1

READ_ONLY = "read-only"

#: The pipelines a session can have active (ARCHITECTURE.md section 4). The
#: prompt gate sets one when the user invokes ``/gatekit-<pipeline>``; the stop
#: and question gates read it. ``discover`` is the optional first step and
#: ``design`` is re-entrant: it may run at any stage, including during a build
#: (ADR-0008). ``doctor`` and ``setup`` are commands, not pipelines, and clear it.
PIPELINES = ("discover", "interview", "mockup", "design", "tasks", "gate", "build", "verify")

Scope = Union[str, List[str]]

#: Session ids come from Claude Code, but the ledger filename is built from
#: them, so anything that is not a safe filename character is replaced.
_UNSAFE_SESSION_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _safe_session_id(session_id: str) -> str:
    """Return a filename-safe form of *session_id*.

    Guards against a hostile or malformed id containing ``/`` or ``..`` and
    escaping the runs directory. Collapsing to a fixed placeholder for an empty
    id keeps the ledger usable rather than raising inside a gate.
    """
    cleaned = _UNSAFE_SESSION_CHARS.sub("_", str(session_id or "")).strip("._")
    return cleaned or "unknown-session"


def _blank(session_id: str) -> Dict[str, Any]:
    now = _now()
    return {
        "version": VERSION,
        "session_id": session_id,
        "created_at": now,
        "updated_at": now,
        "output_lang": "en",
        "active_pipeline": None,
        "questions": {"asked": 0, "max_calls": 2, "budget_exceeded": False},
        "scopes": [],
        "ended_agents": [],
        "stop": {"block_count": 0, "final_verdict": None, "last_reasons": []},
        "events": [],
    }


def _backfill(data: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    """Fill in any key a hand-edited or older ledger is missing."""
    template = _blank(session_id)
    for key, default in template.items():
        if key not in data:
            data[key] = default
        elif isinstance(default, dict) and isinstance(data[key], dict):
            for sub_key, sub_default in default.items():
                data[key].setdefault(sub_key, sub_default)
    data["session_id"] = session_id
    if not isinstance(data.get("events"), list):
        data["events"] = []
    if not isinstance(data.get("scopes"), list):
        data["scopes"] = []
    if not isinstance(data.get("ended_agents"), list):
        data["ended_agents"] = []
    return data


def _normalize(pattern: str) -> str:
    """Normalize a scope entry to a comparable POSIX-relative path.

    Strips ``./`` prefixes and redundant separators so ``./src/auth/**`` and
    ``src/auth/**`` are recognized as the same scope.
    """
    text = str(pattern).strip().replace("\\", "/").lstrip("/")
    if not text:
        return ""
    normalized = posixpath.normpath(text)
    # normpath eats a trailing "/**" into "/**" correctly but turns "." into ".";
    # restore a trailing slash-star form that normpath would have collapsed.
    if text.endswith("/**") and not normalized.endswith("/**"):
        normalized = normalized.rstrip("/") + "/**"
    return "" if normalized == "." else normalized


def _literal_prefix(pattern: str) -> str:
    """Return the leading path segments of *pattern* that contain no wildcard.

    ``src/auth/**`` yields ``src/auth``; ``src/*.ts`` yields ``src``; a pattern
    starting with a wildcard yields ``""`` (matches anywhere).
    """
    segments: List[str] = []
    for segment in pattern.split("/"):
        if any(ch in segment for ch in "*?"):
            break
        segments.append(segment)
    return "/".join(segments)


def _has_wildcard(pattern: str) -> bool:
    return any(ch in pattern for ch in "*?")


def _fnmatch(text: str, pattern: str) -> bool:
    """``fnmatch`` with a bracket read as a letter, the rule the write gate uses:
    ``src/app/[id]/**`` names the folder ``[id]``, not "one of i, d"."""
    return fnmatch.fnmatchcase(text, pattern.replace("[", "[[]"))


def globs_intersect(left: str, right: str) -> bool:
    """True when two write-scope patterns could cover a common path.

    Deciding true glob intersection exactly is undecidable in general, so this
    is a deliberately **conservative heuristic** — it errs toward reporting a
    conflict, because a false conflict costs one re-declared scope while a
    missed conflict costs two agents silently overwriting each other:

    1. identical (after normalization) → intersect;
    2. either pattern matches the other as a literal string (``fnmatch``), which
       covers ``src/auth/**`` against the literal ``src/auth/token.ts``;
    3. either pattern matches the other's literal (wildcard-free) prefix, or one
       literal prefix is a path-prefix of the other — this catches
       ``src/**`` against ``src/auth/*.ts``, where neither side matches the
       other's full text;
    4. a literal path that sits inside a glob's directory prefix intersects that
       glob, so ``src/auth/**`` conflicts with ``src/auth/deep/nested.ts``.

    Non-intersection is reported only when both literal prefixes diverge, which
    is the one case that is genuinely safe to allow.

    Case is ignored: on the case-insensitive file system this kit runs on,
    ``SRC/Auth/**`` and ``src/auth/**`` cover the same files (ADR-0022).
    """
    left_n, right_n = _normalize(left).lower(), _normalize(right).lower()
    if not left_n or not right_n:
        return False
    if left_n == right_n:
        return True

    # (2) direct glob match in either direction.
    if _fnmatch(left_n, right_n) or _fnmatch(right_n, left_n):
        return True

    left_prefix, right_prefix = _literal_prefix(left_n), _literal_prefix(right_n)

    # (3) a glob whose literal prefix is empty can match anything.
    if _has_wildcard(left_n) and not left_prefix:
        return True
    if _has_wildcard(right_n) and not right_prefix:
        return True

    # (3) match either pattern against the other's literal prefix.
    if right_prefix and _fnmatch(right_prefix, left_n):
        return True
    if left_prefix and _fnmatch(left_prefix, right_n):
        return True

    # (4) directory containment between the two literal prefixes.
    if left_prefix and right_prefix:
        if left_prefix == right_prefix:
            return True
        if _is_path_prefix(left_prefix, right_prefix) or _is_path_prefix(
            right_prefix, left_prefix
        ):
            # Containment only counts when the enclosing side is a glob; two
            # distinct literal files never collide.
            return _has_wildcard(left_n) or _has_wildcard(right_n)
    return False


def _is_path_prefix(prefix: str, candidate: str) -> bool:
    """True when *candidate* lies inside directory *prefix*."""
    return candidate == prefix or candidate.startswith(prefix + "/")


def _as_list(scope: Scope) -> List[str]:
    """Normalize a scope field to a list of patterns; ``read-only`` is empty."""
    if isinstance(scope, str):
        return [] if scope.strip() == READ_ONLY else [scope]
    if isinstance(scope, list):
        return [str(item) for item in scope]
    return []


class ScopeLock:
    """A lock file beside the ledger, held across one load-change-save.

    The spawn gate adds a scope while the parent's turn runs; the release hook
    drops one whenever an agent ends, which is at no particular moment of that
    turn. Without a lock, the later ``save`` of two overlapping hooks writes
    back the list it loaded and the other hook's change is lost — a dropped
    *add* would hide a scope from the conflict check.

    ``with ScopeLock(root, session) as held:`` — *held* is ``False`` when the
    lock could not be taken within *wait* seconds. The caller decides what that
    means (the release hook then changes nothing). A lock file older than
    *stale* seconds belongs to a hook that was killed and is taken over.
    """

    def __init__(self, root: pathlib.Path, session_id: str,
                 wait: float = 2.0, stale: float = 15.0) -> None:
        self.path = paths.runs_dir(root) / f"{_safe_session_id(session_id)}.lock"
        self.wait = wait
        self.stale = stale
        self.held = False

    def __enter__(self) -> bool:
        deadline = time.monotonic() + self.wait
        while True:
            try:
                paths.ensure_dir(self.path.parent)
                os.close(os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                self.held = True
                return True
            except OSError:
                pass
            try:
                if time.time() - self.path.stat().st_mtime > self.stale:
                    self.path.unlink()
                    continue
            except OSError:
                pass  # gone in the meantime, or not ours to remove: try again
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def __exit__(self, *exc_info: Any) -> None:
        if self.held:
            self.held = False
            try:
                self.path.unlink()
            except OSError:
                pass


class Ledger:
    """Mutable view over one session's ledger file."""

    def __init__(self, root: pathlib.Path, session_id: str, data: Dict[str, Any]):
        self.root = pathlib.Path(root)
        self.session_id = session_id
        self.data = data

    # -- construction ----------------------------------------------------
    @classmethod
    def path_for(cls, root: pathlib.Path, session_id: str) -> pathlib.Path:
        return paths.runs_dir(root) / f"{_safe_session_id(session_id)}.json"

    @classmethod
    def load(cls, root: pathlib.Path, session_id: str) -> "Ledger":
        """Load the ledger for *session_id*, creating a blank one if absent.

        A corrupt file is replaced by a blank ledger rather than raising: a
        gate that cannot read state must still let the user's session proceed.
        """
        target = cls.path_for(root, session_id)
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("ledger root is not an object")
            data = _backfill(raw, session_id)
        except (OSError, ValueError):
            data = _blank(session_id)
        return cls(root, session_id, data)

    @classmethod
    def exists(cls, root: pathlib.Path, session_id: str) -> bool:
        return cls.path_for(root, session_id).is_file()

    # -- persistence -----------------------------------------------------
    def save(self) -> None:
        """Write the ledger atomically, refreshing ``updated_at``."""
        self.data["updated_at"] = _now()
        config.write_json_atomic(self.path_for(self.root, self.session_id), self.data)

    # -- mutation --------------------------------------------------------
    def append_event(self, kind: str, detail: Optional[Dict[str, Any]] = None) -> None:
        """Append one event, dropping the oldest once past :data:`MAX_EVENTS`."""
        events = self.data.setdefault("events", [])
        events.append({"ts": _now(), "kind": str(kind), "detail": dict(detail or {})})
        if len(events) > MAX_EVENTS:
            del events[: len(events) - MAX_EVENTS]

    def add_scope(self, owner: str, write_scope: Scope,
                  tool_use_id: Optional[str] = None) -> None:
        """Record a write scope claimed by *owner* (an agent label or hash).

        *tool_use_id* is the id of the Agent/Task call that spawns the agent.
        It is the one value the spawn-time event shares with the events that
        report the agent's end, so it is what the scope is released by.
        """
        entry: Dict[str, Any] = {
            "owner": str(owner),
            "write_scope": write_scope,
            "declared_at": _now(),
        }
        if tool_use_id:
            entry["tool_use_id"] = str(tool_use_id)
        self.data.setdefault("scopes", []).append(entry)

    def scope_of(self, key: str, value: str) -> Optional[Dict[str, Any]]:
        """The scope entry whose *key* (one of :data:`SCOPE_KEYS`) equals *value*."""
        if key not in SCOPE_KEYS or not value:
            return None
        for entry in self.data.get("scopes", []):
            if isinstance(entry, dict) and entry.get(key) == value:
                return entry
        return None

    def bind_agent(self, tool_use_id: str, agent_id: str) -> bool:
        """Write *agent_id* on the scope declared by the call *tool_use_id*.

        Returns ``False`` when no scope carries that call id.
        """
        entry = self.scope_of("tool_use_id", tool_use_id)
        if entry is None or not agent_id:
            return False
        entry["agent_id"] = str(agent_id)
        return True

    def release_scope(self, key: str, value: str) -> int:
        """Drop the scope(s) whose *key* equals *value*; return how many.

        *key* is ``tool_use_id`` or ``agent_id``. The match is exact equality on
        an identifier Claude Code issued — never a label, a prompt or a guess —
        so an agent that is still running cannot lose its scope to another
        agent's end.
        """
        if key not in SCOPE_KEYS or not value:
            return 0
        scopes = self.data.get("scopes", [])
        kept = [s for s in scopes if not (isinstance(s, dict) and s.get(key) == value)]
        dropped = len(scopes) - len(kept)
        if dropped:
            owners = [str(s.get("owner", "?")) for s in scopes
                      if isinstance(s, dict) and s.get(key) == value]
            self.data["scopes"] = kept
            self.append_event(
                "scope_released", {"by": key, "id": value, "owners": owners, "count": dropped}
            )
        return dropped

    def note_agent_ended(self, agent_id: str) -> None:
        """Remember that *agent_id* has ended (for a scope that learns its id later)."""
        ended = self.data.setdefault("ended_agents", [])
        if agent_id and agent_id not in ended:
            ended.append(str(agent_id))
            if len(ended) > MAX_ENDED_AGENTS:
                del ended[: len(ended) - MAX_ENDED_AGENTS]

    def agent_ended(self, agent_id: str) -> bool:
        return bool(agent_id) and agent_id in self.data.get("ended_agents", [])

    def release_scopes(self, owner: Optional[str] = None) -> int:
        """Drop recorded scopes by owner label and return how many were dropped.

        The manual step behind ``ledger release-scopes``. The release hook
        (:mod:`gatekit.gates.release`) drops a scope when its agent ends; this
        is for one that was left behind — an agent that failed or was killed
        before its end was reported. ``owner=None`` releases all.
        """
        scopes = self.data.get("scopes", [])
        kept = [] if owner is None else [s for s in scopes if str(s.get("owner")) != owner]
        dropped = len(scopes) - len(kept)
        if dropped:
            self.data["scopes"] = kept
            self.append_event("scopes_released", {"owner": owner or "all", "count": dropped})
        return dropped

    def scope_conflicts(self, write_scope: Scope) -> List[Dict[str, Any]]:
        """Return recorded scopes that intersect *write_scope*.

        ``read-only`` conflicts with nothing in either direction: a reader
        cannot collide with a writer, and two readers cannot collide at all.
        """
        wanted = _as_list(write_scope)
        if not wanted:
            return []
        conflicts: List[Dict[str, Any]] = []
        for entry in self.data.get("scopes", []):
            existing = _as_list(entry.get("write_scope"))
            if not existing:
                continue
            if any(
                globs_intersect(new, old) for new in wanted for old in existing
            ):
                conflicts.append(entry)
        return conflicts

    # -- convenience used by the gates -----------------------------------
    @property
    def output_lang(self) -> str:
        value = self.data.get("output_lang")
        return value if value in ("ko", "en") else "en"

    def set_output_lang(self, value: str) -> None:
        self.data["output_lang"] = value if value in ("ko", "en") else "en"

    def set_pipeline(self, name: Optional[str]) -> bool:
        """Set ``active_pipeline`` to *name* (``None`` clears it).

        Returns ``False`` and leaves the ledger untouched for a name outside
        :data:`PIPELINES`. Entering a *different* pipeline resets the question
        budget: an interview's two questions must not be charged against the
        tasks pipeline that follows it in the same session.
        """
        if name is not None and name not in PIPELINES:
            return False
        previous = self.data.get("active_pipeline")
        self.data["active_pipeline"] = name
        if name != previous:
            self.data["questions"] = {
                "asked": 0,
                "max_calls": 2,
                "budget_exceeded": False,
            }
            self.append_event("pipeline_set", {"pipeline": name, "previous": previous})
        return True


def run(argv: List[str]) -> int:
    """``gatekit.py ledger <show|init|set-pipeline|release-scopes> --session <id>``."""
    import argparse  # CLI only; the hooks that import ledger never parse arguments

    parser = argparse.ArgumentParser(prog="gatekit ledger", add_help=True)
    parser.add_argument("action", choices=["show", "init", "set-pipeline", "release-scopes"])
    parser.add_argument(
        "pipeline",
        nargs="?",
        default=None,
        help="for set-pipeline: one of %s, or 'none'; for release-scopes: an owner "
             "label (default: every scope)" % "/".join(PIPELINES),
    )
    parser.add_argument("--root", default=None, help="project root (default: detected)")
    parser.add_argument("--session", required=True, help="session id")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse already printed the reason
        return int(exc.code or 2)

    root = paths.project_root(args.root)

    if args.action == "init":
        led = Ledger.load(root, args.session)
        led.save()
        print(str(Ledger.path_for(root, args.session)))
        return 0

    if args.action == "release-scopes":
        if not Ledger.exists(root, args.session):
            print(f"gatekit: no ledger for session '{args.session}'", file=sys.stderr)
            return 1
        led = Ledger.load(root, args.session)
        owner = None if not args.pipeline or args.pipeline.lower() == "all" else args.pipeline
        dropped = led.release_scopes(owner)
        led.save()
        print("released %d scope(s)" % dropped)
        return 0

    if args.action == "set-pipeline":
        if not args.pipeline:
            print("gatekit: set-pipeline needs a pipeline name or 'none'", file=sys.stderr)
            return 2
        wanted = None if args.pipeline.lower() == "none" else args.pipeline
        led = Ledger.load(root, args.session)
        if not led.set_pipeline(wanted):
            print(
                "gatekit: unknown pipeline '%s' (expected one of %s, or none)"
                % (args.pipeline, ", ".join(PIPELINES)),
                file=sys.stderr,
            )
            return 2
        led.save()
        print(wanted or "none")
        return 0

    if not Ledger.exists(root, args.session):
        print(f"gatekit: no ledger for session '{args.session}'", file=sys.stderr)
        return 1
    print(json.dumps(Ledger.load(root, args.session).data, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
