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
    try:
        proot = paths.gatekit_root()
    except Exception as exc:
        return _axis("plugin files", verdict.FAIL,
                     "could not locate the plugin root: %s" % exc, "")
    missing = []
    if not (proot / ".claude-plugin" / "plugin.json").is_file():
        missing.append(".claude-plugin/plugin.json")
    if not (proot / "hooks" / "hooks.json").is_file():
        missing.append("hooks/hooks.json")
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
            "reinstall the plugin: /plugin install gatekit",
        )
    return _axis("plugin files", verdict.OK,
                 "plugin.json, hooks.json and %d gate scripts present" % len(GATE_SCRIPTS))


# ------------------------------------------------------------------- axis 2


def _installed_plugins_path():
    home = os.environ.get("HOME")
    if not home:
        return None
    return os.path.join(home, ".claude", "plugins", "installed_plugins.json")


def _settings_path():
    home = os.environ.get("HOME")
    if not home:
        return None
    return os.path.join(home, ".claude", "settings.json")


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _installed_keys(data) -> list:
    """Return the plugin keys (``name@marketplace``) that name gatekit.

    ``installed_plugins.json`` nests entries under ``plugins`` in current
    Claude Code releases; older layouts kept them at the top level. Both are
    read structurally — never by searching the serialized text — so a plugin
    whose description merely mentions gatekit does not count as installed.
    """
    if not isinstance(data, dict):
        return []
    table = data.get("plugins") if isinstance(data.get("plugins"), dict) else data
    keys = []
    for key in table:
        if not isinstance(key, str):
            continue
        name = key.split("@", 1)[0]
        if name == "gatekit":
            keys.append(key)
    return keys


def axis_hooks_registered(root) -> dict:
    path = _installed_plugins_path()
    if not path:
        return _axis("hooks registered", verdict.UNVERIFIED,
                     "HOME is not set; cannot inspect the running install", "")
    if not os.path.isfile(path):
        return _axis("hooks registered", verdict.UNVERIFIED,
                     "no installed_plugins.json under ~/.claude/plugins; "
                     "running from a source checkout?",
                     "/plugin install gatekit")
    try:
        data = _read_json(path)
    except (OSError, ValueError) as exc:
        return _axis("hooks registered", verdict.UNVERIFIED,
                     "installed_plugins.json unreadable: %s" % exc, "")
    keys = _installed_keys(data)
    if not keys:
        return _axis("hooks registered", verdict.FAIL,
                     "gatekit is not listed in installed_plugins.json; "
                     "hooks will not fire",
                     "/plugin install gatekit")

    # Installed is not enabled. A disabled plugin has files on disk and no
    # hooks firing — the state that looks healthy while enforcing nothing.
    settings_path = _settings_path()
    enabled = None
    if settings_path and os.path.isfile(settings_path):
        try:
            settings = _read_json(settings_path)
        except (OSError, ValueError) as exc:
            return _axis("hooks registered", verdict.UNVERIFIED,
                         "installed as %s but settings.json unreadable: %s" % (keys[0], exc), "")
        table = settings.get("enabledPlugins") if isinstance(settings, dict) else None
        if isinstance(table, dict):
            enabled = any(table.get(k) is True for k in keys)
    if enabled is None:
        return _axis("hooks registered", verdict.UNVERIFIED,
                     "installed as %s but no enabledPlugins entry found in settings.json" % keys[0],
                     "/plugin enable %s" % keys[0])
    if not enabled:
        return _axis("hooks registered", verdict.FAIL,
                     "installed as %s but disabled in settings.json enabledPlugins; "
                     "hooks will not fire" % keys[0],
                     "/plugin enable %s" % keys[0])
    return _axis("hooks registered", verdict.OK,
                 "gatekit installed and enabled as %s" % keys[0])


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


# ------------------------------------------------------------------- axis 8


def axis_host_layer(root) -> dict:
    """A generated Codex host layer, when present, must point at real gates.

    Absent is ``ok``: a Claude Code project needs none. Present but broken is
    ``fail``. Whether Codex trusts the project and loads the hooks cannot be
    read from here, and the detail says so.
    """
    from gatekit import hosts

    result = hosts.status(root, "codex")
    if result["verdict"] == verdict.UNVERIFIED:
        return _axis("host layer", verdict.OK, "no Codex host layer (Claude Code plugin serves this project)", "")
    return _axis("host layer", result["verdict"], "codex: " + result["detail"], result.get("fix", ""))


AXES = (
    axis_plugin_files,
    axis_hooks_registered,
    axis_project_state,
    axis_spec_set,
    axis_contract_freshness,
    axis_workers,
    axis_python,
    axis_host_layer,
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
