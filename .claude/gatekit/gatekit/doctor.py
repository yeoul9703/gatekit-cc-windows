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
import sys

from gatekit import paths, verdict

#: Gate scripts that must exist and be non-empty for axis 1.
GATE_SCRIPTS = ("prompt.py", "write.py", "bash.py", "spawn.py", "question.py", "stop.py",
                "compact.py")

#: PowerShell scripts under ``<gatekit root>/scripts`` that axis 1 requires.
POWERSHELL_SCRIPTS = ("common.ps1", "session-check.ps1", "setup.ps1", "verify.ps1")

#: Other files (relative to the gatekit root) that axis 1 requires.
PROJECT_FILES = ("bin/gatekit.py", "pyproject.toml", "uv.lock")

#: Hook events axis 2 expects to find registered in ``.claude/settings.json``.
EXPECTED_HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
                        "PreCompact", "Stop")

#: Fallback when ``scripts/packages.json`` has no readable ``python_min``.
MIN_PYTHON = (3, 14)


def min_python(packages_json=None) -> tuple:
    """``python_min`` of ``scripts/packages.json`` (the single source shared with the
    PowerShell scripts) as ``(major, minor)``; :data:`MIN_PYTHON` if it cannot be read."""
    try:
        path = packages_json or (paths.gatekit_root() / "scripts" / "packages.json")
        with open(path, encoding="utf-8-sig") as fh:
            text = str(json.load(fh).get("python_min", ""))
        match = re.fullmatch(r"(\d+)\.(\d+)", text)
        if match:
            return (int(match.group(1)), int(match.group(2)))
    except (OSError, ValueError, AttributeError):
        pass
    return MIN_PYTHON


#: Output language of the axis texts: "en" (default) or "ko" (``--lang ko``).
_LANG = "en"

#: Korean display names for the axes (the ``axis`` key of the JSON stays English).
AXIS_NAMES_KO = {
    "plugin files": "설치 파일", "hooks registered": "훅 등록", "project state": "프로젝트 상태",
    "spec set": "스펙 묶음", "contract freshness": "완료 계약 최신 여부", "workers": "워커",
    "python": "파이썬", "uv": "uv",
}

#: Hook arguments every PowerShell hook must carry (no profile, no policy block).
REQUIRED_PS_ARGS = ("-NoProfile", "-ExecutionPolicy", "Bypass")


def _t(en, ko):
    return ko if _LANG == "ko" else en


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
                     _t("could not locate the gatekit root: %s", "gatekit 루트를 찾지 못했습니다: %s") % exc, "")
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
            _t("missing or empty: %s", "없거나 비어 있음: %s") % ", ".join(missing),
            _t("restore the missing files from git (git checkout .claude/gatekit)",
               "git 에서 파일을 복원하세요 (git checkout .claude/gatekit)"),
        )
    return _axis("plugin files", verdict.OK,
                 _t("bin/gatekit.py, %d gate scripts, %d PowerShell scripts, pyproject.toml and "
                    "uv.lock present",
                    "bin/gatekit.py, 게이트 스크립트 %d개, PowerShell 스크립트 %d개, "
                    "pyproject.toml, uv.lock 있음") % (len(GATE_SCRIPTS), len(POWERSHELL_SCRIPTS)))


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


def _powershell_hooks_missing_args(hooks):
    """Events whose PowerShell hook lacks ``-NoProfile`` / ``-ExecutionPolicy Bypass``.

    The process execution policy and the user's profile must never decide whether
    a hook runs, so every hook whose command is a PowerShell executable has to
    carry all of :data:`REQUIRED_PS_ARGS` (``-ExecutionPolicy`` followed by ``Bypass``).
    """
    bad = []
    for event in EXPECTED_HOOK_EVENTS:
        for hook in _hook_entries(hooks, event):
            command = str(hook.get("command", "")).replace("\\", "/").split("/")[-1].lower()
            if command not in ("powershell", "powershell.exe", "pwsh", "pwsh.exe"):
                continue
            args = [str(a) for a in hook.get("args") or []]
            lowered = [a.lower() for a in args]
            ok = "-noprofile" in lowered
            if "-executionpolicy" in lowered:
                i = lowered.index("-executionpolicy")
                ok = ok and i + 1 < len(lowered) and lowered[i + 1] == "bypass"
            else:
                ok = False
            if not ok and event not in bad:
                bad.append(event)
    return bad


def axis_hooks_registered(root) -> dict:
    """Standalone mode registers hooks in the project's own
    ``.claude/settings.json`` (no plugin manager, so nothing to enable/disable
    globally). Every expected event must be registered, every hook must be in
    exec form (a shell string would need Git Bash), the gate events must run
    ``bin/gatekit.py``, SessionStart must run ``session-check.ps1`` and every
    PowerShell hook must pass ``-NoProfile -ExecutionPolicy Bypass``."""
    name = "hooks registered"
    restore = _t("restore .claude/settings.json from git", "git 에서 .claude/settings.json 을 복원하세요")
    path = _project_settings_path(root)
    if not os.path.isfile(path):
        return _axis(name, verdict.FAIL,
                     _t("no .claude/settings.json in this project; hooks will not fire",
                        ".claude/settings.json 이 없어 훅이 동작하지 않습니다"), restore)
    try:
        settings = _read_json(path)
    except (OSError, ValueError) as exc:
        return _axis(name, verdict.UNVERIFIED,
                     _t(".claude/settings.json unreadable: %s",
                        ".claude/settings.json 을 읽지 못했습니다: %s") % exc, "")
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    if not isinstance(hooks, dict):
        return _axis(name, verdict.FAIL,
                     _t('.claude/settings.json has no "hooks" object; hooks will not fire',
                        ".claude/settings.json 에 hooks 가 없어 훅이 동작하지 않습니다"), restore)
    missing = [event for event in EXPECTED_HOOK_EVENTS if not _hook_entries(hooks, event)]
    if missing:
        return _axis(name, verdict.FAIL,
                     _t("missing hook registration(s): %s", "등록되지 않은 훅: %s") % ", ".join(missing),
                     restore)
    not_exec = [event for event in EXPECTED_HOOK_EVENTS
                if not all(_is_exec_form(h) for h in _hook_entries(hooks, event))]
    if not_exec:
        return _axis(name, verdict.FAIL,
                     _t("hook(s) not in exec form (command + args, no shell string): %s",
                        "exec 형식(command + args, 셸 문자열 아님)이 아닌 훅: %s") % ", ".join(not_exec),
                     restore)

    def _mentions(event, needle):
        return any(needle in json.dumps(h) for h in _hook_entries(hooks, event))

    wrong = [event for event in EXPECTED_HOOK_EVENTS
             if not _mentions(event, "scripts/session-check.ps1" if event == "SessionStart"
                              else "bin/gatekit.py")]
    if wrong:
        return _axis(name, verdict.FAIL,
                     _t("hooks do not run the expected script for: %s",
                        "예상한 스크립트를 실행하지 않는 훅: %s") % ", ".join(wrong), restore)
    no_flags = _powershell_hooks_missing_args(hooks)
    if no_flags:
        return _axis(name, verdict.FAIL,
                     _t("PowerShell hook(s) missing -NoProfile -ExecutionPolicy Bypass: %s",
                        "PowerShell 훅에 -NoProfile -ExecutionPolicy Bypass 가 없습니다: %s")
                     % ", ".join(no_flags), restore)
    return _axis(name, verdict.OK,
                 _t("all %d hook events registered in exec form (no shell)",
                    "훅 이벤트 %d개가 모두 exec 형식(셸 없음)으로 등록됨") % len(EXPECTED_HOOK_EVENTS))


# ------------------------------------------------------------------- axis 3


def axis_project_state(root) -> dict:
    state = paths.state_dir(root)
    if not state.is_dir():
        return _axis("project state", verdict.UNVERIFIED,
                     _t("no .gatekit/ in this project yet", "이 프로젝트에 아직 .gatekit/ 이 없습니다"),
                     _t("/gatekit:setup  (creates .gatekit/config.json)",
                        "/gatekit:setup  (.gatekit/config.json 을 만듭니다)"))
    problems = []
    cfg = state / "config.json"
    if cfg.is_file():
        try:
            with cfg.open(encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                problems.append(_t("config.json is not a JSON object", "config.json 이 JSON 객체가 아닙니다"))
        except (OSError, ValueError) as exc:
            problems.append(_t("config.json invalid: %s", "config.json 이 올바르지 않습니다: %s") % exc)
    approvals = state / "approvals.json"
    if approvals.is_file():
        try:
            with approvals.open(encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict) or not isinstance(loaded.get("approvals"), list):
                problems.append(_t("approvals.json has no `approvals` list",
                                   "approvals.json 에 `approvals` 목록이 없습니다"))
        except (OSError, ValueError) as exc:
            problems.append(_t("approvals.json invalid: %s", "approvals.json 이 올바르지 않습니다: %s") % exc)
    if problems:
        return _axis("project state", verdict.FAIL, "; ".join(problems),
                     _t("fix or delete the offending file under .gatekit/",
                        ".gatekit/ 안의 문제 파일을 고치거나 지우세요"))
    return _axis("project state", verdict.OK,
                 _t(".gatekit/ present and parseable", ".gatekit/ 이 있고 읽을 수 있습니다"))


# ------------------------------------------------------------------- axis 4


def axis_spec_set(root) -> dict:
    if not paths.spec_dir(root).is_dir():
        return _axis("spec set", verdict.UNVERIFIED,
                     _t("no spec/ directory in this project", "이 프로젝트에 spec/ 폴더가 없습니다"),
                     "/gatekit:interview")
    try:
        from gatekit import spec as spec_mod
        result = spec_mod.validate(root)
    except Exception as exc:
        return _axis("spec set", verdict.UNVERIFIED,
                     _t("spec validation could not run: %s", "스펙 검증을 실행하지 못했습니다: %s") % exc, "")
    v = result.get("verdict", verdict.UNVERIFIED)
    findings = result.get("findings") or []
    bad = [f for f in findings if f.get("verdict") in (verdict.FAIL, verdict.WARN)]
    detail = _t("%d finding(s)", "발견 %d건") % len(findings)
    if bad:
        if _LANG == "ko":
            detail += ": " + ", ".join(str(f.get("file", "?")) for f in bad[:3])
        else:
            detail += ": " + "; ".join(
                "%s %s" % (f.get("file", "?"), f.get("message", "")) for f in bad[:3]
            )
    return _axis("spec set", v, detail,
                 (paths.cli_invocation() + " spec validate") if v != verdict.OK else "")


# ------------------------------------------------------------------- axis 5


def axis_contract_freshness(root) -> dict:
    name = "contract freshness"
    try:
        from gatekit import contract as contract_mod
        v = contract_mod.status(root)
    except Exception as exc:
        return _axis(name, verdict.UNVERIFIED,
                     _t("contract status could not run: %s", "계약 상태를 확인하지 못했습니다: %s") % exc, "")
    if v == verdict.OK:
        return _axis(name, verdict.OK,
                     _t(".gatekit/contract.json matches spec/05-gate.md",
                        ".gatekit/contract.json 이 spec/05-gate.md 와 일치합니다"))
    if v == verdict.UNVERIFIED:
        return _axis(name, verdict.UNVERIFIED,
                     _t("no .gatekit/contract.json yet", "아직 .gatekit/contract.json 이 없습니다"),
                     paths.cli_invocation() + " contract derive")
    try:
        changed = contract_mod.stale_inputs(root)
    except Exception:  # noqa: BLE001 — a diagnosis must never crash doctor
        changed = []
    if changed:
        detail = _t("contract is stale: %s changed since it was derived",
                    "계약이 낡았습니다: 만든 뒤 %s 이(가) 바뀌었습니다") % ", ".join(changed)
    else:
        detail = _t("contract is stale: spec/05-gate.md changed since it was derived",
                    "계약이 낡았습니다: 만든 뒤 spec/05-gate.md 가 바뀌었습니다")
    return _axis(name, verdict.FAIL, detail, paths.cli_invocation() + " contract derive")


# ------------------------------------------------------------------- axis 6


def axis_workers(root) -> dict:
    try:
        from gatekit import workers as workers_mod
        name = workers_mod.default_name(root)
        result = workers_mod.check(root, name)
    except Exception as exc:
        return _axis("workers", verdict.UNVERIFIED,
                     _t("worker check could not run: %s", "워커 점검을 실행하지 못했습니다: %s") % exc, "")
    v = result.get("verdict", verdict.UNVERIFIED)
    fix = ""
    if v == verdict.FAIL:
        fix = _t("install the %s CLI, or: %s workers set-default <name>",
                 "%s CLI 를 설치하거나 다음을 실행하세요: %s workers set-default <이름>") % (
                     name, paths.cli_invocation())
    if _LANG == "ko":
        summary = {verdict.OK: "실행 확인됨", verdict.FAIL: "PATH 에서 찾지 못함",
                   verdict.WARN: "확인이 필요함"}.get(v, "실행 여부를 확인하지 못함")
        return _axis("workers", v, "기본 워커 %s: %s" % (name, summary), fix)
    return _axis("workers", v, "default backend %s — %s" % (name, result.get("detail", "")), fix)


# ------------------------------------------------------------------- axis 7


def _venv_python(kit):
    return kit / ".venv" / "Scripts" / "python.exe"


def _venv_version(kit):
    """``(major, minor, micro)`` from ``.venv/pyvenv.cfg``, or ``None``.

    uv writes ``version_info = 3.14.3``; the stdlib ``venv`` module writes
    ``version = 3.14.3``. Reading the file avoids spawning the interpreter.
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
    setup_fix = _t("/gatekit:setup  (or: uv sync --project .claude/gatekit --frozen)",
                   "/gatekit:setup  (또는: uv sync --project .claude/gatekit --frozen)")
    try:
        kit = paths.gatekit_root()
    except Exception as exc:
        return _axis("python", verdict.FAIL,
                     _t("could not locate the gatekit root: %s", "gatekit 루트를 찾지 못했습니다: %s") % exc, "")
    if not _venv_python(kit).is_file():
        return _axis("python", verdict.FAIL,
                     _t(".claude/gatekit/.venv/Scripts/python.exe is missing, so every gatekit "
                        "hook is silently inactive",
                        ".claude/gatekit/.venv/Scripts/python.exe 가 없어 gatekit 훅이 모두 조용히 꺼져 있습니다"),
                     setup_fix)
    version = _venv_version(kit)
    if version is None:
        return _axis("python", verdict.UNVERIFIED,
                     _t(".venv exists but its version could not be read from pyvenv.cfg",
                        ".venv 는 있지만 pyvenv.cfg 에서 버전을 읽지 못했습니다"), setup_fix)
    text = "%d.%d.%d" % version
    wanted = min_python()
    if version[:2] < wanted:
        return _axis("python", verdict.FAIL,
                     _t("venv python %s is below the required %d.%d",
                        ".venv 의 파이썬 %s 이(가) 필요한 %d.%d 보다 낮습니다") % (text, *wanted),
                     _t("rebuild the venv: /gatekit:setup (-Install venv), or delete "
                        ".claude/gatekit/.venv and run uv sync --project .claude/gatekit --frozen",
                        ".venv 를 다시 만드세요: /gatekit:setup (-Install venv), 또는 .claude/gatekit/.venv 를 지운 뒤 "
                        "uv sync --project .claude/gatekit --frozen"))
    return _axis("python", verdict.OK, _t("venv python %s", ".venv 파이썬 %s") % text)


def axis_uv(root) -> dict:
    """uv must be on PATH: it builds the venv and runs the user-facing commands."""
    found = shutil.which("uv")
    if not found:
        return _axis("uv", verdict.FAIL, _t("uv is not on PATH", "PATH 에 uv 가 없습니다"),
                     _t("winget install --id=astral-sh.uv -e  (ask the user first; /gatekit:setup "
                        "explains it)",
                        "/gatekit:setup 을 실행하세요 (설치는 사용자에게 먼저 묻습니다). "
                        "직접 하려면: winget install --id=astral-sh.uv -e"))
    try:
        proc = subprocess.run(paths.resolve_argv(["uv", "--version"]), capture_output=True,
                              timeout=15)
    except (OSError, subprocess.SubprocessError) as exc:
        return _axis("uv", verdict.UNVERIFIED,
                     _t("uv found at %s but --version failed: %s",
                        "uv 를 %s 에서 찾았지만 --version 이 실패했습니다: %s") % (found, exc), "")
    out = proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode != 0 or not out:
        return _axis("uv", verdict.UNVERIFIED,
                     _t("uv found at %s but --version did not answer",
                        "uv 를 %s 에서 찾았지만 --version 에 답하지 않습니다") % found, "")
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
                           verdict.UNVERIFIED, _t("axis raised %s", "축 실행 중 오류: %s") % exc, "")
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
    global _LANG
    lang = "en"
    if "--lang" in argv:
        i = argv.index("--lang")
        if i + 1 < len(argv):
            lang = argv[i + 1].lower()
    if lang not in ("en", "ko"):
        print("gatekit doctor: --lang must be ko or en", file=sys.stderr)
        return 2
    _LANG = lang
    try:
        return _run(argv, root_arg)
    finally:
        _LANG = "en"


def _run(argv: list, root_arg) -> int:
    root = paths.project_root(root_arg)
    report = diagnose(root)

    if "--json" in argv:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(_t("gatekit doctor — %s (root: %s)", "gatekit 닥터 — %s (루트: %s)")
              % (report["verdict"], root))
        for axis in report["axes"]:
            shown = AXIS_NAMES_KO.get(axis["axis"], axis["axis"]) if _LANG == "ko" else axis["axis"]
            print("  %d. %-11s %-10s %s" % (axis["n"], axis["verdict"], shown, axis["detail"]))
            if axis.get("fix"):
                print(_t("       fix: %s", "       해결: %s") % axis["fix"])
    return 1 if any(a["verdict"] == verdict.FAIL for a in report["axes"]) else 0
