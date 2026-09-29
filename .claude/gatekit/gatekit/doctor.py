"""7-axis diagnosis (§12).

Each axis returns `{"axis", "verdict", "detail", "fix"}` where `fix` is a
copy-pasteable command or "". The overall verdict is `verdict.aggregate` over
the axes, so a single `unverified` axis never rounds the report to `ok`.
Exit code is 1 iff any axis is `fail`.
"""
from __future__ import annotations

import json
import os
import sys

from gatekit import paths, verdict

#: Gate scripts that must exist and be non-empty for axis 1.
GATE_SCRIPTS = ("prompt.py", "write.py", "bash.py", "spawn.py", "question.py", "stop.py")

#: Hook events axis 2 expects to find registered in the running install.
EXPECTED_HOOK_EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")

MIN_PYTHON = (3, 9)


def _axis(name, v, detail, fix=""):
    return {"axis": name, "verdict": v, "detail": detail, "fix": fix}


# ------------------------------------------------------------------- axis 1


def axis_plugin_files(root) -> dict:
    """Standalone layout check: bin/gatekit, bin/gatekit.py and the gate
    scripts must exist under ``<root>/.claude/gatekit``. There is no plugin
    manager in standalone mode, so nothing is "installed" — the files simply
    have to be present on disk, checked out with the rest of the project."""
    try:
        proot = paths.gatekit_root()
    except Exception as exc:
        return _axis("plugin files", verdict.FAIL,
                     "could not locate the gatekit root: %s" % exc, "")
    missing = []
    if not (proot / "bin" / "gatekit").is_file():
        missing.append("bin/gatekit")
    if not (proot / "bin" / "gatekit.py").is_file():
        missing.append("bin/gatekit.py")
    gates = proot / "gatekit" / "gates"
    for script in GATE_SCRIPTS:
        path = gates / script
        if not path.is_file():
            missing.append("gatekit/gates/%s" % script)
        elif path.stat().st_size == 0:
            missing.append("gatekit/gates/%s (empty)" % script)
    if missing:
        return _axis(
            "plugin files", verdict.FAIL,
            "missing or empty: %s" % ", ".join(missing),
            "restore the missing files from git (git checkout .claude/gatekit)",
        )
    return _axis("plugin files", verdict.OK,
                 "bin/gatekit, bin/gatekit.py and %d gate scripts present" % len(GATE_SCRIPTS))


# ------------------------------------------------------------------- axis 2


def _project_settings_path(root):
    return os.path.join(str(root), ".claude", "settings.json")


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def axis_hooks_registered(root) -> dict:
    """Standalone mode registers hooks in the project's own
    ``.claude/settings.json`` (no plugin manager, so nothing to enable/disable
    globally) — this axis just checks that every expected hook event routes
    through ``bin/gatekit``."""
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
    missing = [event for event in EXPECTED_HOOK_EVENTS if not hooks.get(event)]
    if missing:
        return _axis("hooks registered", verdict.FAIL,
                     "missing hook registration(s): %s" % ", ".join(missing),
                     "restore .claude/settings.json from git")
    as_text = json.dumps(hooks)
    if "bin/gatekit" not in as_text:
        return _axis("hooks registered", verdict.FAIL,
                     "hooks are registered but do not call bin/gatekit",
                     "restore .claude/settings.json from git")
    return _axis("hooks registered", verdict.OK,
                 "all %d hook events registered via bin/gatekit" % len(EXPECTED_HOOK_EVENTS))


# ------------------------------------------------------------------- axis 3


def axis_project_state(root) -> dict:
    state = paths.state_dir(root)
    if not state.is_dir():
        return _axis("project state", verdict.UNVERIFIED,
                     "no .gatekit/ in this project yet",
                     paths.cli_invocation() + " doctor --root <project>  # after /gatekit:setup")
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


def axis_python(root) -> dict:
    info = sys.version_info
    current = "%d.%d.%d" % (info.major, info.minor, info.micro)
    if (info.major, info.minor) < MIN_PYTHON:
        return _axis("python", verdict.FAIL,
                     "python %s is below the required %d.%d" % (current, *MIN_PYTHON),
                     "install python 3.9 or newer")
    return _axis("python", verdict.OK, "python %s" % current)


AXES = (
    axis_plugin_files,
    axis_hooks_registered,
    axis_project_state,
    axis_spec_set,
    axis_contract_freshness,
    axis_workers,
    axis_python,
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
