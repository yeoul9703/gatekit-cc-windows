"""8-axis diagnosis (§12).

Each axis returns `{"axis", "verdict", "detail", "fix"}` where `fix` is a
copy-pasteable command or "". The overall verdict is `verdict.aggregate` over
the axes, so a single `unverified` axis never rounds the report to `ok`.
Exit code is 1 iff any axis is `fail`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from gatekit import paths, verdict

#: Gate scripts that must exist and be non-empty for axis 1.
GATE_SCRIPTS = ("prompt.py", "write.py", "bash.py", "spawn.py", "question.py", "stop.py",
                "compact.py")

#: PowerShell scripts under ``<gatekit root>/scripts`` that axis 1 requires.
POWERSHELL_SCRIPTS = ("session-check.ps1", "setup.ps1", "verify.ps1")

#: Other files (relative to the gatekit root) that axis 1 requires.
PROJECT_FILES = ("bin/gatekit.py", "pyproject.toml", "uv.lock")

#: Hook events axis 2 expects to find registered in ``.claude/settings.json``.
EXPECTED_HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                        "PreCompact", "Stop")

#: The venv's interpreter must be at least this (``requires-python`` in pyproject.toml).
MIN_PYTHON = (3, 11)


def _axis(name, v, detail, fix=""):
    return {"axis": name, "verdict": v, "detail": detail, "fix": fix}


# ------------------------------------------------------------------- axis 1


def axis_plugin_files(root) -> dict:
    """Standalone layout check: ``bin/gatekit.py``, the seven gate scripts, the
    three ``scripts/*.ps1``, ``pyproject.toml`` and ``uv.lock`` must exist and be
    non-empty under ``<root>/.claude/gatekit``. There is no plugin manager in
    standalone mode, so nothing is "installed" — the files simply have to be
    present on disk, checked out with the rest of the project."""
    try:
        proot = paths.gatekit_root()
    except Exception as exc:
        return _axis("plugin files", verdict.FAIL,
                     "could not locate the gatekit root: %s" % exc, "")
    wanted = list(PROJECT_FILES)
    wanted += ["gatekit/gates/%s" % name for name in GATE_SCRIPTS]
    wanted += ["scripts/%s" % name for name in POWERSHELL_SCRIPTS]
    missing = []
    for rel in wanted:
        path = proot.joinpath(*rel.split("/"))
        if not path.is_file():
            missing.append(rel)
        elif path.stat().st_size == 0:
            missing.append("%s (empty)" % rel)
    if missing:
        return _axis(
            "plugin files", verdict.FAIL,
            "missing or empty: %s" % ", ".join(missing),
            "restore the missing files from git (git checkout .claude/gatekit)",
        )
    return _axis("plugin files", verdict.OK,
                 "bin/gatekit.py, %d gate scripts, %d PowerShell scripts, pyproject.toml and "
                 "uv.lock present" % (len(GATE_SCRIPTS), len(POWERSHELL_SCRIPTS)))


# ------------------------------------------------------------------- axis 2


def _project_settings_path(root):
    return os.path.join(str(root), ".claude", "settings.json")


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _hook_entries(hooks, event):
    """Every individual hook object registered under *event*."""
    entries = []
    for group in hooks.get(event) or []:
        if isinstance(group, dict):
            for hook in group.get("hooks") or []:
                entries.append(hook)
    return entries


def _is_exec_form(hook) -> bool:
    """Exec form: a ``command`` executable plus an ``args`` list, no shell."""
    return (isinstance(hook, dict) and isinstance(hook.get("command"), str)
            and bool(hook.get("command")) and isinstance(hook.get("args"), list))


def axis_hooks_registered(root) -> dict:
    """Standalone mode registers hooks in the project's own
    ``.claude/settings.json`` (no plugin manager, so nothing to enable/disable
    globally). Every expected event must be registered, every hook must be in
    exec form (a shell string would need Git Bash), the gate events must run
    ``bin/gatekit.py`` and SessionStart must run ``session-check.ps1``."""
    path = _project_settings_path(root)
    if not os.path.isfile(path):
        return _axis("hooks registered", verdict.FAIL,
                     "no .claude/settings.json in this project; hooks will not fire",
                     "restore .claude/settings.json from git")
    try:
        settings = _read_json(path)
    except (OSError, ValueError) as exc:
        return _axis("hooks registered", verdict.UNVERIFIED,
                     ".claude/settings.json unreadable: %s" % exc, "")
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    if not isinstance(hooks, dict):
        return _axis("hooks registered", verdict.FAIL,
                     ".claude/settings.json has no \"hooks\" object; hooks will not fire",
                     "restore .claude/settings.json from git")
    missing = [event for event in EXPECTED_HOOK_EVENTS if not _hook_entries(hooks, event)]
    if missing:
        return _axis("hooks registered", verdict.FAIL,
                     "missing hook registration(s): %s" % ", ".join(missing),
                     "restore .claude/settings.json from git")
    not_exec = [event for event in EXPECTED_HOOK_EVENTS
                if not all(_is_exec_form(h) for h in _hook_entries(hooks, event))]
    if not_exec:
        return _axis("hooks registered", verdict.FAIL,
                     "hook(s) not in exec form (command + args, no shell string): %s"
                     % ", ".join(not_exec),
                     "restore .claude/settings.json from git")
    def _mentions(event, needle):
        return any(needle in json.dumps(h) for h in _hook_entries(hooks, event))

    wrong = [event for event in EXPECTED_HOOK_EVENTS
             if not _mentions(event, "scripts/session-check.ps1" if event == "SessionStart"
                              else "bin/gatekit.py")]
    if wrong:
        return _axis("hooks registered", verdict.FAIL,
                     "hooks do not run the expected script for: %s" % ", ".join(wrong),
                     "restore .claude/settings.json from git")
    return _axis("hooks registered", verdict.OK,
                 "all %d hook events registered in exec form (no shell)"
                 % len(EXPECTED_HOOK_EVENTS))


# ------------------------------------------------------------------- axis 3


def axis_project_state(root) -> dict:
    state = paths.state_dir(root)
    if not state.is_dir():
        return _axis("project state", verdict.UNVERIFIED,
                     "no .gatekit/ in this project yet",
                     "/gatekit:setup  (creates .gatekit/config.json)")
    problems = []
    cfg = state / "config.json"
    if cfg.is_file():
        try:
            with cfg.open(encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                problems.append("config.json is not a JSON object")
        except (OSError, ValueError) as exc:
            problems.append("config.json invalid: %s" % exc)
    approvals = state / "approvals.json"
    if approvals.is_file():
        try:
            with approvals.open(encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict) or not isinstance(loaded.get("approvals"), list):
                problems.append("approvals.json has no `approvals` list")
        except (OSError, ValueError) as exc:
            problems.append("approvals.json invalid: %s" % exc)
    if problems:
        return _axis("project state", verdict.FAIL, "; ".join(problems),
                     "fix or delete the offending file under .gatekit/")
    return _axis("project state", verdict.OK, ".gatekit/ present and parseable")


# ------------------------------------------------------------------- axis 4


def axis_spec_set(root) -> dict:
    if not paths.spec_dir(root).is_dir():
        return _axis("spec set", verdict.UNVERIFIED, "no spec/ directory in this project",
                     "/gatekit:interview")
    try:
        from gatekit import spec as spec_mod
        result = spec_mod.validate(root)
    except Exception as exc:
        return _axis("spec set", verdict.UNVERIFIED,
                     "spec validation could not run: %s" % exc, "")
    v = result.get("verdict", verdict.UNVERIFIED)
    findings = result.get("findings") or []
    bad = [f for f in findings if f.get("verdict") in (verdict.FAIL, verdict.WARN)]
    detail = "%d finding(s)" % len(findings)
    if bad:
        detail += ": " + "; ".join(
            "%s %s" % (f.get("file", "?"), f.get("message", "")) for f in bad[:3]
        )
    return _axis("spec set", v, detail,
                 (paths.cli_invocation() + " spec validate") if v != verdict.OK else "")


# ------------------------------------------------------------------- axis 5


def axis_contract_freshness(root) -> dict:
    try:
        from gatekit import contract as contract_mod
        v = contract_mod.status(root)
    except Exception as exc:
        return _axis("contract freshness", verdict.UNVERIFIED,
                     "contract status could not run: %s" % exc, "")
    if v == verdict.OK:
        return _axis("contract freshness", verdict.OK,
                     ".gatekit/contract.json matches spec/05-gate.md")
    if v == verdict.UNVERIFIED:
        return _axis("contract freshness", verdict.UNVERIFIED,
                     "no .gatekit/contract.json yet",
                     paths.cli_invocation() + " contract derive")
    try:
        changed = contract_mod.stale_inputs(root)
    except Exception:  # noqa: BLE001 — a diagnosis must never crash doctor
        changed = []
    if changed:
        detail = "contract is stale: %s changed since it was derived" % ", ".join(changed)
    else:
        detail = "contract is stale: spec/05-gate.md changed since it was derived"
    return _axis("contract freshness", verdict.FAIL, detail,
                 paths.cli_invocation() + " contract derive")


# ------------------------------------------------------------------- axis 6


def axis_workers(root) -> dict:
    try:
        from gatekit import workers as workers_mod
        name = workers_mod.default_name(root)
        result = workers_mod.check(root, name)
    except Exception as exc:
        return _axis("workers", verdict.UNVERIFIED,
                     "worker check could not run: %s" % exc, "")
    v = result.get("verdict", verdict.UNVERIFIED)
    fix = ""
    if v == verdict.FAIL:
        fix = "install the %s CLI, or: %s workers set-default <name>" % (name, paths.cli_invocation())
    return _axis("workers", v, "default backend %s — %s" % (name, result.get("detail", "")), fix)


# ------------------------------------------------------------------- axis 7


def _venv_python(kit):
    return kit / ".venv" / "Scripts" / "python.exe"


def _venv_version(kit):
    """``(major, minor, micro)`` from ``.venv/pyvenv.cfg``, or ``None``.

    uv writes ``version_info = 3.14.3``; the stdlib ``venv`` module writes
    ``version = 3.11.9``. Reading the file avoids spawning the interpreter.
    """
    try:
        with open(str(kit / ".venv" / "pyvenv.cfg"), "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    match = re.search(r"^version(?:_info)?\s*=\s*(\d+)\.(\d+)(?:\.(\d+))?", text, re.M)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)


def axis_python(root) -> dict:
    """The project venv's interpreter (the one every hook runs) must exist and
    be at least :data:`MIN_PYTHON`."""
    setup_fix = "/gatekit:setup  (or: uv sync --project .claude/gatekit --frozen)"
    try:
        kit = paths.gatekit_root()
    except Exception as exc:
        return _axis("python", verdict.FAIL, "could not locate the gatekit root: %s" % exc, "")
    if not _venv_python(kit).is_file():
        return _axis("python", verdict.FAIL,
                     ".claude/gatekit/.venv/Scripts/python.exe is missing, so every gatekit "
                     "hook is silently inactive", setup_fix)
    version = _venv_version(kit)
    if version is None:
        return _axis("python", verdict.UNVERIFIED,
                     ".venv exists but its version could not be read from pyvenv.cfg", setup_fix)
    text = "%d.%d.%d" % version
    if version[:2] < MIN_PYTHON:
        return _axis("python", verdict.FAIL,
                     "venv python %s is below the required %d.%d" % (text, *MIN_PYTHON),
                     "rebuild the venv: uv sync --project .claude/gatekit --frozen "
                     "(delete .claude/gatekit/.venv first)")
    return _axis("python", verdict.OK, "venv python %s" % text)


def axis_uv(root) -> dict:
    """uv must be on PATH: it builds the venv and runs the user-facing commands."""
    found = shutil.which("uv")
    if not found:
        return _axis("uv", verdict.FAIL, "uv is not on PATH",
                     "winget install --id=astral-sh.uv -e  (ask the user first; /gatekit:setup "
                     "explains it)")
    try:
        proc = subprocess.run(paths.resolve_argv(["uv", "--version"]), capture_output=True,
                              timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return _axis("uv", verdict.UNVERIFIED, "uv found at %s but --version failed: %s"
                     % (found, exc), "")
    out = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not out:
        return _axis("uv", verdict.UNVERIFIED,
                     "uv found at %s but --version did not answer" % found, "")
    return _axis("uv", verdict.OK, out)


AXES = (
    axis_plugin_files,
    axis_hooks_registered,
    axis_project_state,
    axis_spec_set,
    axis_contract_freshness,
    axis_workers,
    axis_python,
    axis_uv,
)


def diagnose(root) -> dict:
    axes = []
    for index, fn in enumerate(AXES, start=1):
        try:
            result = fn(root)
        except Exception as exc:  # an axis must never abort the report
            result = _axis(getattr(fn, "__name__", "axis %d" % index),
                           verdict.UNVERIFIED, "axis raised %s" % exc, "")
        result["n"] = index
        axes.append(result)
    return {"verdict": verdict.aggregate([a["verdict"] for a in axes]), "axes": axes}


# --------------------------------------------------------------------------- CLI


def run(argv: list) -> int:
    argv = list(argv)
    root_arg = None
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            root_arg = argv[i + 1]
    root = paths.project_root(root_arg)
    report = diagnose(root)

    if "--json" in argv:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("gatekit doctor — %s (root: %s)" % (report["verdict"], root))
        for axis in report["axes"]:
            print("  %d. %-11s %-10s %s" % (
                axis["n"], axis["verdict"], axis["axis"], axis["detail"]))
            if axis.get("fix"):
                print("       fix: %s" % axis["fix"])
    return 1 if any(a["verdict"] == verdict.FAIL for a in report["axes"]) else 0
