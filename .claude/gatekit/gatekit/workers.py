"""Worker backends (§9, §10).

A backend is a named argv prefix that runs an agent non-interactively; the
prompt arrives on stdin. Backends come from `.gatekit/config.json`
(`worker.backends`) deep-merged over `config.DEFAULTS`, so a fresh project has
`claude` enabled without any file on disk. A project may add its own backend
entries (e.g. for another CLI) in `.gatekit/config.json`.

Unsafe-flag rule: an argv that contains any of UNSAFE_MARKERS (a bypass /
dangerous / yolo switch) must opt in explicitly with `"unsafe": true`. `resolve`
raises ValueError otherwise, so a job can never silently spawn an unsandboxed
worker.
"""
from __future__ import annotations

import json

import shutil
import subprocess
import sys
from typing import Optional

from gatekit import config, paths, verdict

#: Substrings that mark an argv as sandbox-bypassing. Matched case-insensitively
#: against every argv element.
UNSAFE_MARKERS = ("bypass", "dangerously", "--yolo")

VERSION_PROBE_TIMEOUT_S = 5.0

#: A live probe sends one trivial prompt through the backend's read-only argv.
#: It is what catches "binary present, cannot answer" — not logged in, or a
#: sandbox that hides the credentials — before a build spends its budget.
PROBE_TIMEOUT_S = 60.0
PROBE_PROMPT = "Reply with the single word READY and nothing else.\n"


def _is_unsafe_argv(argv) -> bool:
    for item in argv or ():
        low = str(item).lower()
        for marker in UNSAFE_MARKERS:
            if marker in low:
                return True
    return False


def backends(root) -> dict:
    """All configured backends, name -> backend dict (without the name key)."""
    cfg = config.load(root)
    worker = cfg.get("worker") or {}
    found = worker.get("backends") or {}
    return found if isinstance(found, dict) else {}


def default_name(root) -> str:
    cfg = config.load(root)
    worker = cfg.get("worker") or {}
    name = worker.get("default")
    return name if isinstance(name, str) and name else "claude"


def evaluator_choice(root, host: Optional[str] = None) -> tuple:
    """``(reviewer_name, warning)`` for ``/gatekit-verify`` (ADR-0023).

    The reviewer is ``"agent"`` — a read-only subagent of the host — unless the
    project set ``verify.evaluator`` to a backend. What keeps the judgement
    apart from the work is that the criteria were approved and hash-pinned
    before the code was written and that the reviewer never saw the building
    session, not that a second model exists; so a project with one model is the
    normal case and carries no warning.

    A backend named in ``verify.evaluator`` is used when it is enabled and has
    a ``read_only_argv``. When it is not, the reviewer falls back to
    ``"agent"`` and the reason is returned, so a setting that silently does
    nothing is said out loud. *host* is accepted for callers that pass it and
    no longer changes the answer.
    """
    del host
    cfg = config.load(root)
    value = (cfg.get("verify") or {}).get("evaluator")
    name = value.strip() if isinstance(value, str) else ""
    if not name or name == "agent":
        return "agent", ""
    entry = ((cfg.get("worker") or {}).get("backends") or {}).get(name)
    if isinstance(entry, dict) and entry.get("enabled") and entry.get("read_only_argv"):
        return name, ""
    return "agent", (
        "verify.evaluator names %r, which is not an enabled backend with a "
        "read_only_argv; the host's read-only subagent reviews instead" % name
    )


def evaluator_name(root, host: Optional[str] = None) -> str:
    """``verify.evaluator``: ``"agent"`` or a backend name."""
    return evaluator_choice(root, host)[0]


def resolve(root, name: Optional[str] = None, read_only: bool = False) -> dict:
    """Return the backend dict for `name` (or the configured default).

    The result always carries `name`, `argv`, `enabled`, `unsafe` and
    `read_only`. With *read_only* the returned `argv` is the backend's
    `read_only_argv`; a backend without one cannot be an evaluator, and the
    writable argv is never substituted for it.
    Raises ValueError for an unknown backend, an empty/invalid argv, a disabled
    backend, or an unsafe argv that has not set `"unsafe": true`.
    """
    all_backends = backends(root)
    resolved_name = name or default_name(root)
    entry = all_backends.get(resolved_name)
    if entry is None:
        known = ", ".join(sorted(all_backends)) or "(none)"
        raise ValueError(
            "unknown worker backend %r; configured: %s" % (resolved_name, known)
        )
    if not isinstance(entry, dict):
        raise ValueError("backend %r is not an object in config" % resolved_name)

    key = "read_only_argv" if read_only else "argv"
    argv = entry.get(key)
    if read_only and argv is None:
        raise ValueError(
            "backend %r has no read_only_argv, so it cannot act as the evaluator; "
            "add one to .gatekit/config.json" % resolved_name
        )
    if not isinstance(argv, list) or not argv or not all(
        isinstance(a, str) and a for a in argv
    ):
        raise ValueError("backend %r has an empty or non-string %s" % (resolved_name, key))

    unsafe = bool(entry.get("unsafe", False))
    if _is_unsafe_argv(argv) and not unsafe:
        raise ValueError(
            "backend %r argv contains a sandbox-bypass flag; it must declare "
            '"unsafe": true in .gatekit/config.json to be usable' % resolved_name
        )

    enabled = bool(entry.get("enabled", False))
    if not enabled:
        raise ValueError(
            ("backend %r is disabled; run: " + paths.cli_invocation() + " workers enable %s")
            % (resolved_name, resolved_name)
        )

    out = dict(entry)
    out["name"] = resolved_name
    out["argv"] = list(argv)
    out["enabled"] = enabled
    out["unsafe"] = unsafe
    out["read_only"] = read_only
    return out


def _live_probe(root, name: str, exe: str) -> dict:
    """Run one prompt through the backend; ``ok`` only when it answers."""
    entry = backends(root).get(name) or {}
    argv = entry.get("read_only_argv") or entry.get("argv") or []
    argv = [exe] + [str(a) for a in argv[1:]]
    try:
        proc = subprocess.run(
            argv,
            input=PROBE_PROMPT.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=PROBE_TIMEOUT_S,
            cwd=str(root),
        )
    except subprocess.TimeoutExpired:
        return {"name": name, "verdict": verdict.UNVERIFIED,
                "detail": "%s found; live probe gave no answer within %ds" % (name, int(PROBE_TIMEOUT_S))}
    except OSError as exc:
        return {"name": name, "verdict": verdict.UNVERIFIED,
                "detail": "%s found; live probe could not run (%s)" % (name, exc)}
    tail = (proc.stdout or b"").decode("utf-8", "replace").strip().replace("\n", " ")[-240:]
    if proc.returncode != 0:
        return {"name": name, "verdict": verdict.FAIL,
                "detail": "%s found but a live probe exited %d — it cannot run a prompt here (not logged in, or sandboxed away from its credentials): %s"
                % (name, proc.returncode, tail)}
    return {"name": name, "verdict": verdict.OK,
            "detail": "%s answered a live probe via %s: %s" % (name, " ".join(argv[1:]) or "(no args)", tail[:120])}


def check(root, name: str, probe: bool = False) -> dict:
    """Probe a backend's executable. `{"name", "verdict", "detail"}`.

    fail        — argv[0] is not on PATH (or the backend is unknown/misconfigured);
                  with *probe*, also when a live prompt exits non-zero
    ok          — on PATH and `argv[0] --version` exited 0; with *probe*, the
                  backend answered one prompt through its read_only_argv
    unverified  — on PATH but the version probe failed, errored or timed out;
                  with *probe*, the live prompt timed out
    """
    all_backends = backends(root)
    entry = all_backends.get(name)
    if not isinstance(entry, dict):
        return {
            "name": name,
            "verdict": verdict.FAIL,
            "detail": "no such backend in .gatekit/config.json",
        }
    argv = entry.get("argv")
    if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
        return {"name": name, "verdict": verdict.FAIL, "detail": "invalid argv"}

    exe = shutil.which(argv[0])
    if not exe:
        return {
            "name": name,
            "verdict": verdict.FAIL,
            "detail": "%s not found on PATH" % argv[0],
        }

    try:
        proc = subprocess.run(
            [exe, "--version"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=VERSION_PROBE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "verdict": verdict.UNVERIFIED,
            "detail": "%s found at %s; --version timed out after %ss"
            % (argv[0], exe, int(VERSION_PROBE_TIMEOUT_S)),
        }
    except OSError as exc:
        return {
            "name": name,
            "verdict": verdict.UNVERIFIED,
            "detail": "%s found at %s; --version could not run (%s)" % (argv[0], exe, exc),
        }

    if probe:
        return _live_probe(root, name, exe)

    text = (proc.stdout or b"").decode("utf-8", "replace").strip().splitlines()
    first = text[0][:120] if text else ""
    if proc.returncode != 0:
        return {
            "name": name,
            "verdict": verdict.UNVERIFIED,
            "detail": "%s found at %s; --version exited %d" % (argv[0], exe, proc.returncode),
        }
    return {
        "name": name,
        "verdict": verdict.OK,
        "detail": "%s at %s%s" % (argv[0], exe, (" — " + first) if first else ""),
    }


def _set_backend_flag(root, name: str, key: str, value) -> dict:
    cfg = config.load(root)
    worker = cfg.setdefault("worker", {})
    entries = worker.setdefault("backends", {})
    entry = entries.get(name)
    if not isinstance(entry, dict):
        raise ValueError("unknown worker backend %r" % name)
    entry[key] = value
    config.save(root, cfg)
    return cfg


# --------------------------------------------------------------------------- CLI


def _usage() -> str:
    return (
        "usage: python3 -m gatekit workers <command>\n"
        "  list [--json]          show every backend, its argv and state\n"
        "  default                print the default backend name\n"
        "  check <name> [--probe] probe the executable; --probe also sends one prompt through it\n"
        "  set-default <name>     make <name> the default worker backend\n"
        "  enable <name>          enable a backend\n"
        "  set-evaluator <name>   who grades in verify: agent (default) or a backend name\n"
    )


def _root_from(argv: list) -> tuple:
    """Pop an optional `--root PATH` out of argv; return (root, rest)."""
    rest, root_arg = [], None
    i = 0
    while i < len(argv):
        if argv[i] == "--root" and i + 1 < len(argv):
            root_arg = argv[i + 1]
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    return paths.project_root(root_arg), rest


def run(argv: list) -> int:
    root, argv = _root_from(list(argv))
    if not argv or argv[0] in ("-h", "--help", "help"):
        sys.stdout.write(_usage())
        return 0 if argv else 1

    cmd, rest = argv[0], argv[1:]

    if cmd == "list":
        as_json = "--json" in rest
        entries = backends(root)
        default = default_name(root)
        rows = []
        for name in sorted(entries):
            entry = entries[name] if isinstance(entries[name], dict) else {}
            rows.append(
                {
                    "name": name,
                    "argv": entry.get("argv", []),
                    "enabled": bool(entry.get("enabled", False)),
                    "unsafe": bool(entry.get("unsafe", False)),
                    "default": name == default,
                }
            )
        if as_json:
            ev, why = evaluator_choice(root)
            print(json.dumps({"default": default, "evaluator": ev,
                              "evaluator_warning": why, "backends": rows}, indent=2))
        else:
            for row in rows:
                mark = "*" if row["default"] else " "
                state = "enabled" if row["enabled"] else "disabled"
                if row["unsafe"]:
                    state += ", unsafe"
                print("%s %-10s [%s] %s" % (mark, row["name"], state, " ".join(row["argv"])))
            ev, why = evaluator_choice(root)
            print("evaluator: %s" % ev)
            if why:
                # ADR-0023: a named backend that cannot review is said out loud.
                print("  warn: %s" % why)
        return 0

    if cmd == "default":
        # Just the name, so a caller can use it without parsing `list --json`.
        print(default_name(root))
        return 0

    if cmd == "check":
        if not rest:
            print("workers check: missing <name>", file=sys.stderr)
            return 2
        result = check(root, rest[0], probe="--probe" in rest)
        if "--json" in rest:
            print(json.dumps(result, indent=2))
        else:
            print("%s %s — %s" % (result["verdict"], result["name"], result["detail"]))
        return 1 if result["verdict"] == verdict.FAIL else 0

    if cmd in ("set-default", "enable"):
        if not rest:
            print("workers %s: missing <name>" % cmd, file=sys.stderr)
            return 2
        name = rest[0]
        entries = backends(root)
        if name not in entries:
            print("workers %s: unknown backend %r" % (cmd, name), file=sys.stderr)
            return 2
        if cmd == "enable":
            entry = entries[name] if isinstance(entries[name], dict) else {}
            if _is_unsafe_argv(entry.get("argv") or []) and not entry.get("unsafe"):
                print(
                    "workers enable: %r declares a sandbox-bypass flag without "
                    '"unsafe": true; refusing' % name,
                    file=sys.stderr,
                )
                return 2
            _set_backend_flag(root, name, "enabled", True)
            print("ok enabled %s" % name)
        else:
            cfg = config.load(root)
            cfg.setdefault("worker", {})["default"] = name
            config.save(root, cfg)
            print("ok default worker backend is now %s" % name)
        return 0

    if cmd == "set-evaluator":
        if not rest:
            print("workers set-evaluator: missing <name>", file=sys.stderr)
            return 2
        name = rest[0]
        if name != "agent" and name not in backends(root):
            print("workers set-evaluator: unknown evaluator %r (agent or a backend name)" % name, file=sys.stderr)
            return 2
        cfg = config.load(root)
        cfg.setdefault("verify", {})["evaluator"] = name
        config.save(root, cfg)
        print("ok evaluator is now %s" % name)
        return 0

    print("workers: unknown command %r\n" % cmd, file=sys.stderr)
    sys.stderr.write(_usage())
    return 2
