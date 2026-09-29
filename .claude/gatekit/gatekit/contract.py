"""The executable completion contract.

"Done" is not a claim an agent gets to make in prose. It is a list of commands
that either exit as expected or do not. Criteria are declared in
``spec/05-gate.md`` as ```` ```gatekit-criterion ```` JSON fences, frozen into
``.gatekit/contract.json`` by :func:`derive`, and executed by :func:`execute`.

Three rules keep the result honest:

* **Timeouts are ``unverified``, never ``ok`` and never ``fail``.** A command
  that ran out of time told us nothing about the code.
* **Artifacts must stay inside the project root**, checked after
  ``os.path.realpath`` so a symlink cannot point the evidence somewhere else.
* **A stale contract short-circuits to ``unverified``.** If ``05-gate.md`` or
  any recorded design input (:data:`INPUT_FILES`) changed after derivation, the
  frozen criteria no longer describe the agreed-upon gate, so running them would
  answer the wrong question.

Commands run through ``subprocess.run`` with no shell: ``argv`` is a list and
stays a list, so a criterion cannot smuggle in shell metacharacters.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from . import approval, config, paths, verdict

VERSION = 1

#: Total wall-clock budget for a whole contract run (ARCHITECTURE.md section 5).
#: A project whose suite is honestly slower may raise it with a
#: ``gatekit-budget`` fence in spec/05-gate.md, up to MAX_BUDGET_S. Without
#: that escape hatch a slow-but-passing suite is permanently `unverified`.
TOTAL_BUDGET_S = 45.0

#: Ceiling for a declared budget. A Stop-gate run that can outlast the user's
#: patience is worse than one that reports `unverified` and stands down.
MAX_BUDGET_S = 600.0

#: Per-criterion default when the fence omits ``timeout_s``.
DEFAULT_TIMEOUT_S = 30

#: How much of stdout/stderr is retained per criterion.
TAIL_CHARS = 2000

#: Everything ``expect`` may say. ``exit`` is an integer; the ``*_contains``
#: and ``*_not_contains`` keys take a string or a list of strings (all must
#: hold); the ``*_regex`` keys take one pattern searched with re.MULTILINE.
#: Output expectations are judged over the whole stream, not the stored tail.
#: An unknown key is a derive error, so a typo cannot become a silent pass.
EXPECT_KEYS = (
    "exit",
    "stdout_contains",
    "stdout_not_contains",
    "stdout_regex",
    "stderr_contains",
    "stderr_not_contains",
    "stderr_regex",
)


def _as_str_list(value: Any) -> Optional[List[str]]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    return None


def validate_expect(expect: Any, ident: str = "?") -> List[str]:
    """Problems with an ``expect`` object, as messages; empty when valid.

    Shared by ``derive`` (which refuses) and ``spec validate`` (which reports)
    so the two can never disagree about what a criterion may say.
    """
    if not isinstance(expect, dict):
        return ["criterion '%s': 'expect' must be an object" % ident]
    problems: List[str] = []
    for key, value in expect.items():
        if key not in EXPECT_KEYS:
            problems.append(
                "criterion '%s': unknown expect key '%s' (allowed: %s)" % (ident, key, ", ".join(EXPECT_KEYS))
            )
        elif key == "exit":
            if isinstance(value, bool) or not isinstance(value, int):
                problems.append("criterion '%s': expect.exit must be an integer" % ident)
        elif key.endswith("_regex"):
            if not isinstance(value, str):
                problems.append("criterion '%s': expect.%s must be a string" % (ident, key))
            else:
                try:
                    re.compile(value)
                except re.error as err:
                    problems.append("criterion '%s': expect.%s is not a valid regex: %s" % (ident, key, err))
        elif _as_str_list(value) is None:
            problems.append("criterion '%s': expect.%s must be a string or a list of strings" % (ident, key))
    return problems


def judge_output(expect: Dict[str, Any], stdout: str, stderr: str) -> List[str]:
    """Expectations over the streams that did not hold; empty means all held."""
    streams = {"stdout": stdout or "", "stderr": stderr or ""}
    failures: List[str] = []
    for key, value in expect.items():
        if key == "exit" or key not in EXPECT_KEYS:
            continue
        stream_name, _, kind = key.partition("_")
        text = streams[stream_name]
        if kind == "regex":
            if not re.search(value, text, re.MULTILINE):
                failures.append("expect.%s did not match: %r" % (key, value))
        elif kind == "contains":
            for needle in _as_str_list(value) or []:
                if needle not in text:
                    failures.append("expect.%s missing: %r" % (key, needle))
        elif kind == "not_contains":
            for needle in _as_str_list(value) or []:
                if needle in text:
                    failures.append("expect.%s matched: %r" % (key, needle))
    return failures

FENCE_NAME = "gatekit-criterion"

#: Optional single fence declaring the run-wide budget.
BUDGET_FENCE_NAME = "gatekit-budget"

STALE_REASON = "contract_stale"

# Matches a fenced block whose info string is exactly the fence name. The
# opening fence must start at the beginning of a line, which keeps prose that
# merely mentions the fence name out of the results.
_FENCE_RE = re.compile(
    r"^[ \t]*```[ \t]*(?P<name>[A-Za-z0-9_-]+)[ \t]*\r?\n(?P<body>.*?)^[ \t]*```[ \t]*$",
    re.DOTALL | re.MULTILINE,
)


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def parse_fences(text: str, name: str) -> List[Dict[str, Any]]:
    """Return the JSON objects of every ```` ```<name> ```` fence in *text*.

    Raises :class:`ValueError` naming the fence index when a block does not
    parse, so the user learns which one to fix rather than getting a bare
    "invalid JSON".
    """
    results: List[Dict[str, Any]] = []
    index = 0
    for match in _FENCE_RE.finditer(text or ""):
        if match.group("name") != name:
            continue
        index += 1
        body = match.group("body")
        try:
            parsed = json.loads(body)
        except ValueError as err:
            raise ValueError(f"{name} fence #{index} is not valid JSON: {err}") from err
        if not isinstance(parsed, dict):
            raise ValueError(f"{name} fence #{index} must contain a JSON object")
        results.append(parsed)
    return results


def _normalize_criterion(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    """Validate one criterion and fill in its defaults."""
    ident = raw.get("id")
    if not isinstance(ident, str) or not ident.strip():
        raise ValueError(f"criterion #{index} is missing a non-empty string 'id'")

    argv = raw.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError(f"criterion '{ident}' needs 'argv' as a non-empty list of strings")

    expect = raw.get("expect")
    if expect is None:
        expect = {"exit": 0}
    problems = validate_expect(expect, ident.strip() if isinstance(ident, str) else "?")
    if problems:
        raise ValueError("; ".join(problems))
    expect = dict(expect)
    expect.setdefault("exit", 0)

    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []

    try:
        timeout_s = float(raw.get("timeout_s", DEFAULT_TIMEOUT_S))
    except (TypeError, ValueError):
        timeout_s = float(DEFAULT_TIMEOUT_S)
    if timeout_s <= 0:
        timeout_s = float(DEFAULT_TIMEOUT_S)

    return {
        "id": ident.strip(),
        "argv": list(argv),
        "expect": expect,
        "timeout_s": timeout_s,
        "artifacts": [str(a) for a in artifacts],
    }


def gate_file(root: pathlib.Path) -> pathlib.Path:
    return paths.spec_dir(root) / "05-gate.md"


#: The design files a build is judged against alongside ``05-gate.md``
#: (ADR-0008 decision 6). A worker builds against these, so a change to one of
#: them makes the frozen contract describe a design that no longer exists.
#: Absent files hash to ``""``, which is a real recorded value: creating one
#: later is as much a change as editing one.
INPUT_FILES = ("spec/02-screens.md", "spec/02-design.md", "spec/tokens.json")


def input_hashes(root: pathlib.Path) -> Dict[str, str]:
    """Current sha256 of every contract input, ``""`` for the absent ones."""
    return {
        rel: approval.sha256_file(pathlib.Path(root) / rel) for rel in INPUT_FILES
    }


def stale_inputs(root: pathlib.Path) -> List[str]:
    """Input paths whose content differs from what ``derive`` recorded.

    Empty for a fresh contract, for no contract at all, and for one derived
    before inputs were recorded — those are judged on the gate file alone, so
    there is nothing here to report.
    """
    data = load(root)
    if data is None:
        return []
    recorded = data.get("inputs")
    if not isinstance(recorded, dict):
        return []
    current = input_hashes(root)
    return [rel for rel in INPUT_FILES if current.get(rel, "") != recorded.get(rel, "")]


def _parse_budget(text: str) -> float:
    """Return the declared total budget, or the default when none is declared."""
    fences = parse_fences(text, BUDGET_FENCE_NAME)
    if not fences:
        return TOTAL_BUDGET_S
    if len(fences) > 1:
        raise ValueError(
            "spec/05-gate.md declares %d %s fences; exactly one is allowed"
            % (len(fences), BUDGET_FENCE_NAME)
        )
    raw = fences[0].get("total_budget_s")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("%s needs a numeric 'total_budget_s'" % BUDGET_FENCE_NAME)
    value = float(raw)
    if value <= 0:
        raise ValueError("total_budget_s must be greater than 0, got %g" % value)
    if value > MAX_BUDGET_S:
        raise ValueError(
            "total_budget_s %g exceeds the %g second ceiling; a gate that runs "
            "longer should be a build step, not a stop-gate check"
            % (value, MAX_BUDGET_S)
        )
    return value


def derive(root: pathlib.Path) -> Dict[str, Any]:
    """Parse ``spec/05-gate.md`` into ``.gatekit/contract.json`` and return it."""
    source = gate_file(root)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as err:
        raise FileNotFoundError(f"cannot read {source}: {err}") from err

    total_budget_s = _parse_budget(text)
    raw_criteria = parse_fences(text, FENCE_NAME)
    criteria = [_normalize_criterion(item, i + 1) for i, item in enumerate(raw_criteria)]

    seen = set()
    for crit in criteria:
        if crit["id"] in seen:
            raise ValueError(f"duplicate criterion id '{crit['id']}'")
        seen.add(crit["id"])

    data = {
        "version": VERSION,
        "source_sha256": approval.sha256_file(source),
        "inputs": input_hashes(root),
        "total_budget_s": total_budget_s,
        "criteria": criteria,
        "derived_at": _now(),
    }
    config.write_json_atomic(paths.contract_file(root), data)
    return data


def load(root: pathlib.Path) -> Optional[Dict[str, Any]]:
    """Read ``.gatekit/contract.json``, or ``None`` when absent/corrupt."""
    try:
        raw = json.loads(paths.contract_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def status(root: pathlib.Path) -> str:
    """``ok`` when fresh, ``fail`` when stale, ``unverified`` when absent.

    Fresh means the gate file **and** every recorded design input still hash to
    what ``derive`` froze. A contract written before inputs were recorded has no
    ``inputs`` key and is judged on the gate file alone, exactly as before.
    """
    data = load(root)
    if data is None:
        return verdict.UNVERIFIED
    current = approval.sha256_file(gate_file(root))
    if not current:
        return verdict.FAIL
    if current != data.get("source_sha256"):
        return verdict.FAIL
    return verdict.FAIL if stale_inputs(root) else verdict.OK


def _tail(text: str) -> str:
    """Keep the last :data:`TAIL_CHARS` characters — errors live at the end."""
    if text is None:
        return ""
    text = str(text)
    if len(text) <= TAIL_CHARS:
        return text
    return "…(truncated)…" + text[-TAIL_CHARS:]


def _artifact_hashes(
    root: pathlib.Path, artifacts: List[str]
) -> "tuple[Dict[str, str], List[str]]":
    """Hash each artifact, reporting any that is missing or escapes the root.

    Containment is checked on the realpath so a symlink pointing outside the
    project cannot be presented as evidence produced inside it.
    """
    hashes: Dict[str, str] = {}
    problems: List[str] = []
    real_root = os.path.realpath(str(root))

    for entry in artifacts:
        rel = str(entry)
        if os.path.isabs(rel):
            problems.append(f"artifact must be relative: {rel}")
            continue
        if ".." in pathlib.PurePosixPath(rel.replace("\\", "/")).parts:
            problems.append(f"artifact must not contain '..': {rel}")
            continue

        candidate = pathlib.Path(root) / rel
        real = os.path.realpath(str(candidate))
        if real != real_root and not real.startswith(real_root + os.sep):
            problems.append(f"artifact escapes the project root: {rel}")
            continue
        if not os.path.isfile(real):
            problems.append(f"missing artifact: {rel}")
            continue

        digest = approval.sha256_file(pathlib.Path(real))
        if not digest:
            problems.append(f"unreadable artifact: {rel}")
            continue
        hashes[rel] = digest

    return hashes, problems


def _run_one(
    root: pathlib.Path, crit: Dict[str, Any], remaining: float
) -> Dict[str, Any]:
    """Execute one criterion and classify the outcome."""
    result: Dict[str, Any] = {
        "id": crit["id"],
        "verdict": verdict.UNVERIFIED,
        "exit": None,
        "elapsed_s": 0.0,
        "stdout_tail": "",
        "stderr_tail": "",
        "artifact_hashes": {},
    }

    if remaining <= 0:
        result["stderr_tail"] = "budget exhausted before this criterion ran"
        return result

    timeout = min(float(crit.get("timeout_s", DEFAULT_TIMEOUT_S)), remaining)
    started = time.monotonic()
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, shell=False by default
            list(crit["argv"]),
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        result["elapsed_s"] = round(time.monotonic() - started, 3)
        result["stderr_tail"] = f"timeout after {timeout:.1f}s"
        return result  # stays unverified
    except (OSError, ValueError) as err:
        # Missing binary, permission denied, bad argv: we learned nothing about
        # the code under test, so this is unverified rather than a failure.
        result["elapsed_s"] = round(time.monotonic() - started, 3)
        result["stderr_tail"] = f"could not execute: {err}"
        return result

    result["elapsed_s"] = round(time.monotonic() - started, 3)
    result["exit"] = completed.returncode
    result["stdout_tail"] = _tail(completed.stdout)
    result["stderr_tail"] = _tail(completed.stderr)

    expect = crit.get("expect", {}) or {}
    expected_exit = expect.get("exit", 0)
    if completed.returncode != expected_exit:
        result["verdict"] = verdict.FAIL
        return result

    unmet = judge_output(expect, completed.stdout, completed.stderr)
    if unmet:
        result["verdict"] = verdict.FAIL
        result["stderr_tail"] = _tail(
            (result["stderr_tail"] + "\n" + "; ".join(unmet)).strip()
        )
        return result

    hashes, problems = _artifact_hashes(root, crit.get("artifacts", []))
    result["artifact_hashes"] = hashes
    if problems:
        result["verdict"] = verdict.FAIL
        result["stderr_tail"] = _tail(
            (result["stderr_tail"] + "\n" + "; ".join(problems)).strip()
        )
        return result

    result["verdict"] = verdict.OK
    return result


def execute(
    root: pathlib.Path,
    total_budget_s: Optional[float] = None,
    cap_s: Optional[float] = None,
) -> Dict[str, Any]:
    """Run every criterion within *total_budget_s* and aggregate the verdict.

    *cap_s* lowers whatever budget applies (declared or explicit) to at most
    that many seconds. The stop gate uses it so a run never outlives the hook
    timeout Claude Code gives it; a run cut short by the cap is ``unverified``,
    which is honest, where a killed hook would record nothing at all.

    Returns ``{"verdict", "criteria", "reasons"}``. ``reasons`` holds short
    human-readable strings naming what failed or went unverified; the stop gate
    puts them in front of the user.
    """
    data = load(root)
    if data is None:
        return {
            "verdict": verdict.UNVERIFIED,
            "criteria": [],
            "reasons": ["no contract: run `gatekit contract derive` first"],
        }

    if status(root) != verdict.OK:
        return {
            "verdict": verdict.UNVERIFIED,
            "criteria": [],
            "reasons": [STALE_REASON],
        }

    criteria = data.get("criteria") or []
    if not criteria:
        return {
            "verdict": verdict.UNVERIFIED,
            "criteria": [],
            "reasons": ["contract has no criteria"],
        }

    if total_budget_s is None:
        declared = data.get("total_budget_s")
        budget = float(declared) if isinstance(declared, (int, float)) and not isinstance(declared, bool) else TOTAL_BUDGET_S
    else:
        budget = float(total_budget_s)
    if cap_s is not None:
        budget = min(budget, float(cap_s))
    deadline = time.monotonic() + budget
    results: List[Dict[str, Any]] = []
    for crit in criteria:
        results.append(_run_one(root, crit, deadline - time.monotonic()))

    reasons: List[str] = []
    for item in results:
        if item["verdict"] == verdict.FAIL:
            reasons.append(f"{item['id']}: fail (exit {item['exit']})")
        elif item["verdict"] == verdict.UNVERIFIED:
            detail = item.get("stderr_tail") or "not verified"
            reasons.append(f"{item['id']}: unverified ({detail.strip().splitlines()[0][:120]})")

    return {
        "verdict": verdict.aggregate(results),
        "criteria": results,
        "total_budget_s": budget,
        "reasons": reasons,
    }


def run(argv: List[str]) -> int:
    """``gatekit contract derive|status|run [--json]``."""
    parser = argparse.ArgumentParser(prog="gatekit contract", add_help=True)
    parser.add_argument("action", choices=["derive", "status", "run"])
    parser.add_argument("--root", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--budget", type=float, default=None,
                        help="override the contract's declared total budget (seconds)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)

    root = paths.project_root(args.root)

    if args.action == "derive":
        try:
            data = derive(root)
        except (FileNotFoundError, ValueError) as err:
            print(f"gatekit: {err}", file=sys.stderr)
            return 1
        if args.as_json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"derived {len(data['criteria'])} criteria -> {paths.contract_file(root)}")
        return 0

    if args.action == "status":
        result = status(root)
        changed = stale_inputs(root)
        if changed:
            # Naming the file saves the user from diffing three of them to find
            # out why the gate they approved no longer applies.
            print("%s (changed inputs: %s)" % (result, ", ".join(changed)))
        else:
            print(result)
        return 0 if result == verdict.OK else 1

    result = execute(root, total_budget_s=args.budget)
    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result["verdict"])
        for reason in result["reasons"]:
            print(f"  - {reason}")
    return 0 if result["verdict"] == verdict.OK else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))
